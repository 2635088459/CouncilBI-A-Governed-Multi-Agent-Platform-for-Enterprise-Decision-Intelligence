"""Typed RAG v2 contracts and small deterministic helpers.

This file maps spec/version2/08-rag.spec.md into plain Python objects. It does
not talk to PostgreSQL or a vector database yet; it gives the rest of the
system one clear vocabulary for document indexing and evidence retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4


DocumentType = Literal[
    "weekly_report",
    "release_note",
    "campaign",
    "ticket",
    "incident",
    "finance_report",
]


class RagWarningCode(StrEnum):
    NO_EVIDENCE = "RAG_NO_EVIDENCE"


class IndexJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start_at: datetime | None = None
    end_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.start_at is not None and self.end_at is not None and self.start_at > self.end_at:
            raise ValueError("time_window start_at must be before or equal to end_at")

    def contains(self, value: datetime) -> bool:
        if self.start_at is not None and value < self.start_at:
            return False
        if self.end_at is not None and value > self.end_at:
            return False
        return True


@dataclass(frozen=True, slots=True)
class IndexDocumentRequest:
    document_id: str
    source: str
    title: str
    document_type: DocumentType
    published_at: datetime
    business_tags: tuple[str, ...]
    permission_tags: tuple[str, ...]
    text: str

    def __post_init__(self) -> None:
        _require_text(self.document_id, "document_id")
        _require_text(self.source, "source")
        _require_text(self.title, "title")
        if not 1 <= len(self.text) <= 500_000:
            raise ValueError("text length must be between 1 and 500000 characters")
        _require_non_empty_tags(self.business_tags, "business_tags")
        _require_non_empty_tags(self.permission_tags, "permission_tags")

    @property
    def requires_async_indexing(self) -> bool:
        return len(self.text) > 50_000


@dataclass(frozen=True, slots=True)
class RagDocument:
    document_id: str
    source: str
    title: str
    document_type: DocumentType
    published_at: datetime
    business_tags: tuple[str, ...]
    permission_tags: tuple[str, ...]
    org_id: str = "org_legacy"


@dataclass(frozen=True, slots=True)
class RagChunk:
    chunk_id: str
    document_id: str
    position: int
    text: str
    token_count: int
    org_id: str = "org_legacy"

    def __post_init__(self) -> None:
        _require_text(self.chunk_id, "chunk_id")
        _require_text(self.document_id, "document_id")
        if self.position < 1:
            raise ValueError("position must be greater than or equal to 1")
        _require_text(self.text, "text")
        if self.token_count < 1:
            raise ValueError("token_count must be greater than or equal to 1")


@dataclass(frozen=True, slots=True)
class EmbeddingMetadata:
    embedding_id: str
    chunk_id: str
    model_name: str
    model_version: str
    dimensions: int
    org_id: str = "org_legacy"

    def __post_init__(self) -> None:
        _require_text(self.embedding_id, "embedding_id")
        _require_text(self.chunk_id, "chunk_id")
        _require_text(self.model_name, "model_name")
        _require_text(self.model_version, "model_version")
        if self.dimensions < 1:
            raise ValueError("dimensions must be greater than or equal to 1")


@dataclass(frozen=True, slots=True)
class IndexJob:
    job_id: str
    document_id: str
    status: IndexJobStatus
    error_message: str | None = None
    org_id: str = "org_legacy"

    @classmethod
    def queued(cls, document_id: str) -> IndexJob:
        _require_text(document_id, "document_id")
        return cls(
            job_id=f"rag_job_{uuid4().hex}",
            document_id=document_id,
            status=IndexJobStatus.QUEUED,
        )


@dataclass(frozen=True, slots=True)
class EvidenceSearchRequest:
    trace_id: str
    query_text: str
    time_window: TimeWindow | None
    business_tags: tuple[str, ...]
    permission_tags: tuple[str, ...]
    limit: int

    def __post_init__(self) -> None:
        _require_text(self.trace_id, "trace_id")
        _require_text(self.query_text, "query_text")
        if not 1 <= self.limit <= 10:
            raise ValueError("limit must be between 1 and 10")


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    document_id: str
    chunk_id: str
    snippet: str
    source: str
    published_at: datetime
    relevance_score: float

    def __post_init__(self) -> None:
        _require_text(self.evidence_id, "evidence_id")
        _require_text(self.document_id, "document_id")
        _require_text(self.chunk_id, "chunk_id")
        _require_text(self.snippet, "snippet")
        _require_text(self.source, "source")
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError("relevance_score must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    event_id: str
    trace_id: str
    evidence_id: str
    document_id: str
    chunk_id: str
    returned_at: datetime
    org_id: str = "org_legacy"

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_text(self.trace_id, "trace_id")
        _require_text(self.evidence_id, "evidence_id")
        _require_text(self.document_id, "document_id")
        _require_text(self.chunk_id, "chunk_id")


@dataclass(frozen=True, slots=True)
class EvidenceSearchResult:
    evidence_list: tuple[EvidenceItem, ...]
    warnings: tuple[RagWarningCode, ...] = field(default_factory=tuple)

    @classmethod
    def empty_recall(cls) -> EvidenceSearchResult:
        return cls(evidence_list=(), warnings=(RagWarningCode.NO_EVIDENCE,))


def normalize_tags(tags: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Normalize tags once so permission comparisons stay deterministic."""

    normalized = {tag.strip().lower() for tag in tags if tag.strip()}
    return tuple(sorted(normalized))


def permission_tags_allowed(
    document_permission_tags: tuple[str, ...],
    user_permission_tags: tuple[str, ...],
) -> bool:
    """Return True only when the user has every permission required by a doc."""

    required = set(normalize_tags(document_permission_tags))
    allowed = set(normalize_tags(user_permission_tags))
    return required.issubset(allowed)


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_non_empty_tags(tags: tuple[str, ...], field_name: str) -> None:
    if not normalize_tags(tags):
        raise ValueError(f"{field_name} must include at least one non-empty tag")
