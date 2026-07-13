"""Background processing pipeline for uploaded files.

FR-FV10-007: the upload endpoint returns ``status=processing`` immediately;
every reprocessing step below runs asynchronously in this worker.

Structured path (FR-FV10-008/009): download the original bytes, infer schema
with DuckDB, write a Parquet snapshot next to the original file, and record
``schema_json``/``row_count``. Files over the row limit fail without ever
writing a snapshot.

Unstructured path (FR-FV10-010): extract text, chunk it with sentence-aware
overlap, embed each chunk with the configured embedding client, and hand the
vectors to a ``FileVectorSink`` tagged with ``org_id``/``user_id``/``file_id``
so retrieval can enforce per-user scoping later.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from chatbi.core.contracts import new_trace_id
from chatbi.embedding_vector_rag import EmbeddingClient, EmbeddingRequest
from chatbi.files.contracts import UserUploadedFile
from chatbi.files.parser_structured import (
    ParquetWriter,
    RowLimitExceeded,
    SchemaSerializer,
    StructuredFileParser,
)
from chatbi.files.parser_unstructured import SentenceAwareChunker, TextChunk, TextExtractor
from chatbi.files.repository import FileRepository
from chatbi.files.storage import ObjectStorageAdapter, parquet_storage_key


class FileRecordNotFoundError(Exception):
    """Raised when the worker is asked to process an unknown file_id."""


class FileVectorSink(Protocol):
    """Write port for embedded chunks from user-uploaded unstructured files."""

    def upsert_chunks(
        self,
        chunks: tuple[TextChunk, ...],
        vectors: tuple[tuple[float, ...], ...],
    ) -> None: ...


class FileVectorSource(Protocol):
    """Read port used by promotion to copy a file's already-embedded chunks.

    Kept separate from ``FileVectorSink`` (interface segregation): the worker
    only ever writes, promotion only ever reads.
    """

    def chunks_with_vectors_for_file(
        self, file_id: str
    ) -> tuple[tuple[TextChunk, tuple[float, ...]], ...]: ...


def _empty_chunks() -> list[TextChunk]:
    return []


def _empty_vectors() -> list[tuple[float, ...]]:
    return []


@dataclass(slots=True)
class InMemoryFileVectorSink:
    """In-process mock sink for tests and local development."""

    chunks: list[TextChunk] = field(default_factory=_empty_chunks)
    vectors: list[tuple[float, ...]] = field(default_factory=_empty_vectors)

    def upsert_chunks(
        self,
        chunks: tuple[TextChunk, ...],
        vectors: tuple[tuple[float, ...], ...],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        self.chunks.extend(chunks)
        self.vectors.extend(vectors)

    def chunks_for_file(self, file_id: str) -> tuple[TextChunk, ...]:
        return tuple(chunk for chunk in self.chunks if chunk.file_id == file_id)

    def chunks_with_vectors_for_file(
        self, file_id: str
    ) -> tuple[tuple[TextChunk, tuple[float, ...]], ...]:
        return tuple(
            (chunk, vector)
            for chunk, vector in zip(self.chunks, self.vectors, strict=True)
            if chunk.file_id == file_id
        )


class FileProcessingWorker:
    """Runs the FR-FV10-008/009/010 post-upload pipeline for one file."""

    def __init__(
        self,
        *,
        storage: ObjectStorageAdapter,
        repository: FileRepository,
        embedding_client: EmbeddingClient,
        vector_sink: FileVectorSink,
        structured_parser: StructuredFileParser | None = None,
        parquet_writer: ParquetWriter | None = None,
        schema_serializer: SchemaSerializer | None = None,
        text_extractor: TextExtractor | None = None,
        chunker: SentenceAwareChunker | None = None,
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._embedding_client = embedding_client
        self._vector_sink = vector_sink
        self._structured_parser = structured_parser or StructuredFileParser()
        self._parquet_writer = parquet_writer or ParquetWriter()
        self._schema_serializer = schema_serializer or SchemaSerializer()
        self._text_extractor = text_extractor or TextExtractor()
        self._chunker = chunker or SentenceAwareChunker()

    def process(self, file_id: str, *, extension: str) -> UserUploadedFile:
        file = self._repository.get(file_id)
        if file is None:
            raise FileRecordNotFoundError(file_id)

        content_bytes = self._storage.get_object(file.storage_key)
        if file.file_type == "structured":
            return self._process_structured(file, content_bytes, extension)
        return self._process_unstructured(file, content_bytes, extension)

    def _process_structured(
        self,
        file: UserUploadedFile,
        content_bytes: bytes,
        extension: str,
    ) -> UserUploadedFile:
        try:
            table = self._structured_parser.parse(content_bytes, extension)
        except RowLimitExceeded:
            failed = replace(file, status="failed", error_reason="ROW_LIMIT_EXCEEDED")
            self._repository.save(failed)
            return failed

        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        try:
            self._parquet_writer.write(table, temp_path)
            self._storage.put_object(parquet_storage_key(file.storage_key), temp_path.read_bytes())
        finally:
            temp_path.unlink(missing_ok=True)

        ready = replace(
            file,
            status="ready",
            schema_json=self._schema_serializer.to_json(table),
            row_count=table.row_count,
        )
        self._repository.save(ready)
        return ready

    def _process_unstructured(
        self,
        file: UserUploadedFile,
        content_bytes: bytes,
        extension: str,
    ) -> UserUploadedFile:
        indexing = replace(file, status="indexing")
        self._repository.save(indexing)

        text = self._text_extractor.extract(content_bytes, extension)
        chunks = self._chunker.chunk(
            text,
            org_id=file.org_id,
            user_id=file.user_id,
            file_id=file.file_id,
        )

        if chunks:
            embedding_response = self._embedding_client.embed(
                EmbeddingRequest(
                    trace_id=new_trace_id(),
                    org_id=file.org_id,
                    input_texts=tuple(chunk.text for chunk in chunks),
                )
            )
            self._vector_sink.upsert_chunks(chunks, embedding_response.vectors)

        ready = replace(indexing, status="ready", chunk_count=len(chunks))
        self._repository.save(ready)
        return ready
