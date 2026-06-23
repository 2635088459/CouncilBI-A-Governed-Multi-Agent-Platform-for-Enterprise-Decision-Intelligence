"""In-memory knowledge document storage and retrieval for RAG evidence.

This module is deliberately small and deterministic. It gives the project a
local version of the RAG pipeline from spec/08 before a real vector database or
embedding service is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt
from time import perf_counter
from typing import Any, Mapping
import re

from chatbi.core.contracts import EvidenceItem, RetrievalStats


def _empty_metadata() -> Mapping[str, Any]:
    return {}


def _empty_tags() -> tuple[str, ...]:
    return ()


def _empty_roles() -> tuple[str, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    source_id: str
    title: str
    doc_type: str
    publish_time: datetime
    tags: tuple[str, ...] = field(default_factory=_empty_tags)
    allowed_roles: tuple[str, ...] = field(default_factory=_empty_roles)


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    chunk_id: str
    source_id: str
    chunk_index: int
    chunk_text: str
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class ChunkEmbedding:
    embedding_id: str
    chunk_id: str
    embedding_vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeChunkRecord:
    document: KnowledgeDocument
    chunk: DocumentChunk
    embedding: ChunkEmbedding | None = None
    relevance_score: float = 0.0

    def to_evidence_item(self) -> EvidenceItem:
        return EvidenceItem(
            source_id=self.document.source_id,
            title=self.document.title,
            citation_anchor=f"{self.document.source_id}#chunk-{self.chunk.chunk_index}",
            snippet=self.chunk.chunk_text,
            publish_time=self.document.publish_time,
            relevance_score=self.relevance_score,
        )


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """Input contract for online retrieval.

    In the future, ``query_embedding`` can come from a real embedding model.
    For now, the store can create a deterministic local embedding from text.
    """

    question: str
    metric_context: str = ""
    doc_type: str | None = None
    doc_types: tuple[str, ...] = ()
    published_from: datetime | None = None
    published_to: datetime | None = None
    user_role: str | None = None
    tags: tuple[str, ...] = ()
    top_k: int = 5
    query_embedding: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    evidence_list: tuple[EvidenceItem, ...]
    explanation_text: str
    confidence: float
    uncertainty: bool
    retrieval_stats: RetrievalStats
    trace_id: str


class InMemoryKnowledgeStore:
    """Store documents, chunks, and embeddings for local RAG workflows."""

    def __init__(self) -> None:
        self._documents_by_source_id: dict[str, KnowledgeDocument] = {}
        self._chunks_by_chunk_id: dict[str, DocumentChunk] = {}
        self._embeddings_by_chunk_id: dict[str, ChunkEmbedding] = {}

    def save_document(self, document: KnowledgeDocument) -> None:
        self._require_text(document.source_id, "source_id")
        self._require_text(document.title, "title")
        self._require_text(document.doc_type, "doc_type")
        self._documents_by_source_id[document.source_id] = document

    def save_chunk(self, chunk: DocumentChunk) -> None:
        self._require_text(chunk.chunk_id, "chunk_id")
        self._require_text(chunk.source_id, "source_id")
        self._require_text(chunk.chunk_text, "chunk_text")
        if chunk.source_id not in self._documents_by_source_id:
            raise ValueError(f"Unknown document source_id {chunk.source_id}.")
        self._chunks_by_chunk_id[chunk.chunk_id] = chunk

    def save_embedding(self, embedding: ChunkEmbedding) -> None:
        self._require_text(embedding.embedding_id, "embedding_id")
        self._require_text(embedding.chunk_id, "chunk_id")
        if embedding.chunk_id not in self._chunks_by_chunk_id:
            raise ValueError(f"Unknown chunk_id {embedding.chunk_id}.")
        if not embedding.embedding_vector:
            raise ValueError("embedding_vector is required")
        self._embeddings_by_chunk_id[embedding.chunk_id] = embedding

    def ingest_document(
        self,
        document: KnowledgeDocument,
        raw_text: str,
        chunk_size: int = 90,
        chunk_overlap: int = 15,
    ) -> tuple[KnowledgeChunkRecord, ...]:
        """Clean, chunk, embed, and index one document.

        The unit is words instead of tokens because this project does not have
        a tokenizer dependency yet. The shape mirrors the real offline RAG
        flow: document -> clean -> chunk -> embed -> index.
        """

        self.save_document(document)
        chunks = chunk_text(
            clean_document_text(raw_text),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        records: list[KnowledgeChunkRecord] = []
        for index, text in enumerate(chunks, start=1):
            chunk = DocumentChunk(
                chunk_id=f"{document.source_id}_chunk_{index}",
                source_id=document.source_id,
                chunk_index=index,
                chunk_text=text,
            )
            embedding = ChunkEmbedding(
                embedding_id=f"{document.source_id}_embedding_{index}",
                chunk_id=chunk.chunk_id,
                embedding_vector=text_embedding(text),
            )
            self.save_chunk(chunk)
            self.save_embedding(embedding)
            records.append(KnowledgeChunkRecord(document=document, chunk=chunk, embedding=embedding))
        return tuple(records)

    def list_chunk_records(
        self,
        doc_type: str | None = None,
        doc_types: tuple[str, ...] = (),
        published_from: datetime | None = None,
        published_to: datetime | None = None,
        user_role: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> tuple[KnowledgeChunkRecord, ...]:
        records: list[KnowledgeChunkRecord] = []
        for chunk in sorted(
            self._chunks_by_chunk_id.values(),
            key=lambda item: (item.source_id, item.chunk_index),
        ):
            document = self._documents_by_source_id[chunk.source_id]
            if doc_type is not None and document.doc_type != doc_type:
                continue
            if doc_types and document.doc_type not in doc_types:
                continue
            if published_from is not None and document.publish_time < published_from:
                continue
            if published_to is not None and document.publish_time > published_to:
                continue
            if user_role is not None and not self._role_can_read(document, user_role):
                continue
            if tags and not set(tags).issubset(set(document.tags)):
                continue
            records.append(
                KnowledgeChunkRecord(
                    document=document,
                    chunk=chunk,
                    embedding=self._embeddings_by_chunk_id.get(chunk.chunk_id),
                )
            )
        return tuple(records)

    def evidence_items(
        self,
        doc_type: str | None = None,
        doc_types: tuple[str, ...] = (),
        published_from: datetime | None = None,
        published_to: datetime | None = None,
        user_role: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> tuple[EvidenceItem, ...]:
        return tuple(
            record.to_evidence_item()
            for record in self.list_chunk_records(
                doc_type=doc_type,
                doc_types=doc_types,
                published_from=published_from,
                published_to=published_to,
                user_role=user_role,
                tags=tags,
            )
        )

    def retrieve(self, query: RetrievalQuery, trace_id: str = "") -> RetrievalResult:
        """Run filter -> hybrid retrieval -> rerank -> dedupe -> evidence output."""

        started_at = perf_counter()
        filtered_records = self.list_chunk_records(
            doc_type=query.doc_type,
            doc_types=query.doc_types,
            published_from=query.published_from,
            published_to=query.published_to,
            user_role=query.user_role,
            tags=query.tags,
        )
        ranked_records = self._rank_records(filtered_records, query)
        selected_records = self._dedupe_adjacent_chunks(ranked_records[: max(query.top_k * 2, query.top_k)])
        selected_records = selected_records[: query.top_k]
        evidence_list = tuple(record.to_evidence_item() for record in selected_records)
        latency_ms = (perf_counter() - started_at) * 1000
        uncertainty = not evidence_list

        return RetrievalResult(
            evidence_list=evidence_list,
            explanation_text=self._compose_explanation(evidence_list),
            confidence=self._confidence(evidence_list),
            uncertainty=uncertainty,
            retrieval_stats=RetrievalStats(
                candidate_count=len(self._chunks_by_chunk_id),
                filtered_count=len(filtered_records),
                reranked_count=len(ranked_records),
                selected_count=len(evidence_list),
                latency_ms=latency_ms,
            ),
            trace_id=trace_id,
        )

    def _require_text(self, value: str, field_name: str) -> None:
        if not value.strip():
            raise ValueError(f"{field_name} is required")

    def _role_can_read(self, document: KnowledgeDocument, user_role: str) -> bool:
        if not document.allowed_roles:
            return True
        return user_role in document.allowed_roles

    def _rank_records(
        self,
        records: tuple[KnowledgeChunkRecord, ...],
        query: RetrievalQuery,
    ) -> tuple[KnowledgeChunkRecord, ...]:
        query_text = f"{query.question} {query.metric_context}".strip()
        query_tokens = _tokens(query_text)
        query_embedding = query.query_embedding or text_embedding(query_text)
        scored_records: list[KnowledgeChunkRecord] = []

        for record in records:
            keyword_score = _keyword_score(query_tokens, _tokens(record.chunk.chunk_text))
            vector_score = _cosine_similarity(
                query_embedding,
                record.embedding.embedding_vector if record.embedding is not None else text_embedding(record.chunk.chunk_text),
            )
            source_score = _source_weight(record.document.doc_type)
            relevance_score = round((keyword_score * 0.60) + (vector_score * 0.35) + source_score, 4)
            if relevance_score <= 0:
                continue
            scored_records.append(
                KnowledgeChunkRecord(
                    document=record.document,
                    chunk=record.chunk,
                    embedding=record.embedding,
                    relevance_score=relevance_score,
                )
            )

        return tuple(
            sorted(
                scored_records,
                key=lambda item: (
                    item.relevance_score,
                    item.document.publish_time,
                    -item.chunk.chunk_index,
                ),
                reverse=True,
            )
        )

    def _dedupe_adjacent_chunks(
        self,
        records: tuple[KnowledgeChunkRecord, ...],
    ) -> tuple[KnowledgeChunkRecord, ...]:
        if not records:
            return ()

        records_by_doc: dict[str, list[KnowledgeChunkRecord]] = {}
        for record in records:
            records_by_doc.setdefault(record.document.source_id, []).append(record)

        merged_records: list[KnowledgeChunkRecord] = []
        for doc_records in records_by_doc.values():
            sorted_records = sorted(doc_records, key=lambda item: item.chunk.chunk_index)
            current = sorted_records[0]
            for next_record in sorted_records[1:]:
                if next_record.chunk.chunk_index == current.chunk.chunk_index + 1:
                    current = self._merge_records(current, next_record)
                    continue
                merged_records.append(current)
                current = next_record
            merged_records.append(current)

        return tuple(
            sorted(
                merged_records,
                key=lambda item: (item.relevance_score, item.document.publish_time),
                reverse=True,
            )
        )

    def _merge_records(
        self,
        left: KnowledgeChunkRecord,
        right: KnowledgeChunkRecord,
    ) -> KnowledgeChunkRecord:
        merged_text = f"{left.chunk.chunk_text} {right.chunk.chunk_text}"
        merged_chunk = DocumentChunk(
            chunk_id=left.chunk.chunk_id,
            source_id=left.chunk.source_id,
            chunk_index=left.chunk.chunk_index,
            chunk_text=merged_text,
            metadata=left.chunk.metadata,
        )
        return KnowledgeChunkRecord(
            document=left.document,
            chunk=merged_chunk,
            embedding=left.embedding,
            relevance_score=max(left.relevance_score, right.relevance_score),
        )

    def _compose_explanation(self, evidence_list: tuple[EvidenceItem, ...]) -> str:
        if not evidence_list:
            return "No relevant evidence was found, so the explanation is uncertain."

        anchors = ", ".join(item.citation_anchor for item in evidence_list)
        return f"Relevant evidence was found and every returned claim should cite: {anchors}."

    def _confidence(self, evidence_list: tuple[EvidenceItem, ...]) -> float:
        if not evidence_list:
            return 0.2
        return min(0.95, 0.55 + (len(evidence_list) * 0.1))


def clean_document_text(raw_text: str) -> str:
    """Normalize whitespace while preserving the document wording."""

    return re.sub(r"\s+", " ", raw_text).strip()


def chunk_text(
    text: str,
    chunk_size: int = 90,
    chunk_overlap: int = 15,
) -> tuple[str, ...]:
    """Split text into overlapping word chunks for offline indexing."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be greater than or equal to 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    words = text.split()
    if not words:
        return ()

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - chunk_overlap
    return tuple(chunks)


def text_embedding(text: str, dimensions: int = 16) -> tuple[float, ...]:
    """Create a deterministic lightweight embedding from token hashes."""

    if dimensions <= 0:
        raise ValueError("dimensions must be greater than 0")

    vector = [0.0] * dimensions
    for token in _tokens(text):
        bucket = sum(ord(character) for character in token) % dimensions
        vector[bucket] += 1.0
    magnitude = sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return tuple(vector)
    return tuple(value / magnitude for value in vector)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower()))


def _keyword_score(query_tokens: tuple[str, ...], chunk_tokens: tuple[str, ...]) -> float:
    if not query_tokens or not chunk_tokens:
        return 0.0

    query_set = set(query_tokens)
    chunk_set = set(chunk_tokens)
    return len(query_set & chunk_set) / len(query_set)


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right:
        return 0.0

    dimensions = min(len(left), len(right))
    numerator = sum(left[index] * right[index] for index in range(dimensions))
    left_magnitude = sqrt(sum(value * value for value in left[:dimensions]))
    right_magnitude = sqrt(sum(value * value for value in right[:dimensions]))
    if left_magnitude == 0 or right_magnitude == 0:
        return 0.0
    return numerator / (left_magnitude * right_magnitude)


def _source_weight(doc_type: str) -> float:
    weights = {
        "incident": 0.05,
        "incident_report": 0.05,
        "release_note": 0.04,
        "release_notes": 0.04,
        "support_ticket": 0.03,
        "campaign": 0.03,
        "finance_report": 0.03,
        "report": 0.02,
    }
    return weights.get(doc_type, 0.01)
