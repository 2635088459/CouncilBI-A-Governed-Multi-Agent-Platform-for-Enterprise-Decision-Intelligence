import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from chatbi.embedding_vector_rag import MockEmbeddingClient
from chatbi.files import (
    FileProcessingWorker,
    FileRecordNotFoundError,
    InMemoryFileRepository,
    InMemoryFileVectorSink,
    InMemoryObjectStorageAdapter,
    UserUploadedFile,
    parquet_storage_key,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_abc123",
        org_id="org_1",
        user_id="user_1",
        original_name="revenue.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=1024,
        storage_key="org_1/user_1/ufile_abc123/revenue.csv",
        content_hash="hash_abc123",
        status="processing",
        scope="user",
        file_group_id="fgrp_1",
        version_number=1,
        is_latest=True,
        created_at=_now(),
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def _build_worker(
    repository: InMemoryFileRepository,
    storage: InMemoryObjectStorageAdapter,
    vector_sink: InMemoryFileVectorSink | None = None,
) -> FileProcessingWorker:
    return FileProcessingWorker(
        storage=storage,
        repository=repository,
        embedding_client=MockEmbeddingClient(),
        vector_sink=vector_sink or InMemoryFileVectorSink(),
    )


def test_process_structured_file_produces_ready_status_schema_and_parquet_snapshot() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    storage.put_object(file.storage_key, b"id,name,amount\n1,alice,10.5\n2,bob,20.25\n")
    worker = _build_worker(repository, storage)

    result = worker.process(file.file_id, extension="csv")

    assert result.status == "ready"
    assert result.row_count == 2
    # 10-followups/11: the VARCHAR column also carries a value sample
    # (FR-FV10-080) computed by SchemaSerializer during this same
    # processing pass.
    assert result.schema_json == {
        "columns": [
            {"name": "id", "type": "BIGINT"},
            {"name": "name", "type": "VARCHAR", "sample_values": ["alice", "bob"]},
            {"name": "amount", "type": "DOUBLE"},
        ]
    }
    assert repository.get(file.file_id) == result

    parquet_bytes = storage.get_object(parquet_storage_key(file.storage_key))
    connection = duckdb.connect(":memory:")
    try:
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
            temp_file.write(parquet_bytes)
            temp_path = Path(temp_file.name)
        rows = connection.sql(f"SELECT * FROM read_parquet('{temp_path}')").fetchall()
        temp_path.unlink()
    finally:
        connection.close()
    assert rows == [(1, "alice", 10.5), (2, "bob", 20.25)]


def test_process_structured_file_over_row_limit_fails_without_writing_a_snapshot() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = _file()
    repository.save(file)
    header = "id\n"
    data_rows = "".join(f"{i}\n" for i in range(1_000_001))
    storage.put_object(file.storage_key, (header + data_rows).encode("utf-8"))
    worker = _build_worker(repository, storage)

    result = worker.process(file.file_id, extension="csv")

    assert result.status == "failed"
    assert result.error_reason == "ROW_LIMIT_EXCEEDED"
    assert result.schema_json is None
    assert result.row_count is None
    assert not storage.exists(parquet_storage_key(file.storage_key))
    assert repository.get(file.file_id) == result


def test_process_unstructured_file_chunks_embeds_and_tags_every_chunk() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    vector_sink = InMemoryFileVectorSink()
    file = _file(
        file_id="ufile_doc1",
        file_type="unstructured",
        mime_type="text/plain",
        storage_key="org_1/user_1/ufile_doc1/notes.txt",
    )
    repository.save(file)
    storage.put_object(
        file.storage_key,
        b"Quarterly revenue grew twelve percent. Costs stayed flat this quarter.",
    )
    worker = _build_worker(repository, storage, vector_sink)

    result = worker.process(file.file_id, extension="txt")

    assert result.status == "ready"
    assert result.chunk_count is not None
    assert result.chunk_count > 0
    stored_chunks = vector_sink.chunks_for_file(file.file_id)
    assert len(stored_chunks) == result.chunk_count
    assert len(vector_sink.vectors) == len(stored_chunks)
    for chunk in stored_chunks:
        assert chunk.org_id == "org_1"
        assert chunk.user_id == "user_1"
        assert chunk.file_id == "ufile_doc1"


def test_process_unknown_file_id_raises() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    worker = _build_worker(repository, storage)

    with pytest.raises(FileRecordNotFoundError):
        worker.process("ufile_missing", extension="csv")
