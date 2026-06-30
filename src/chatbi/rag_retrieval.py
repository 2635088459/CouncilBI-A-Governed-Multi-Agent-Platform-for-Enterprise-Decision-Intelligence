"""In-memory RAG v2 evidence retrieval.

This module is the small local version of the evidence service from
spec/version2/08-rag.spec.md. It stores already-indexed artifacts, applies the
required filters, ranks matching chunks, and records evidence events by trace id.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from chatbi.rag import (
    EvidenceEvent,
    EvidenceItem,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    RagChunk,
    RagDocument,
    normalize_tags,
    permission_tags_allowed,
)
from chatbi.rag_indexing import IndexArtifacts


@dataclass(frozen=True, slots=True)
class StoredChunk:
    document: RagDocument
    chunk: RagChunk


class InMemoryRagEvidenceStore:
    """A tiny evidence store that makes the RAG retrieval rules explicit."""

    def __init__(self) -> None:
        self._documents_by_id: dict[str, RagDocument] = {}
        self._chunks_by_id: dict[str, RagChunk] = {}
        self._events_by_trace_id: dict[str, tuple[EvidenceEvent, ...]] = {}

    def add_artifacts(self, artifacts: IndexArtifacts) -> None:
        self._documents_by_id[artifacts.document.document_id] = artifacts.document
        for chunk in artifacts.chunks:
            if chunk.document_id != artifacts.document.document_id:
                raise ValueError("chunk document_id must match artifact document_id")
            self._chunks_by_id[chunk.chunk_id] = chunk

    def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        filtered_chunks = tuple(
            stored_chunk
            for stored_chunk in self._stored_chunks()
            if self._matches_filters(stored_chunk.document, request)
        )
        ranked_chunks = self._rank_chunks(filtered_chunks, request.query_text)
        selected_chunks = ranked_chunks[: request.limit]
        if not selected_chunks:
            self._events_by_trace_id[request.trace_id] = ()
            return EvidenceSearchResult.empty_recall()

        evidence_list = tuple(
            self._to_evidence_item(stored_chunk, relevance_score)
            for stored_chunk, relevance_score in selected_chunks
        )
        self._events_by_trace_id[request.trace_id] = tuple(
            EvidenceEvent(
                event_id=f"rag_evt_{request.trace_id}_{index}",
                trace_id=request.trace_id,
                evidence_id=evidence.evidence_id,
                document_id=evidence.document_id,
                chunk_id=evidence.chunk_id,
                returned_at=datetime.now(timezone.utc),
            )
            for index, evidence in enumerate(evidence_list, start=1)
        )
        return EvidenceSearchResult(evidence_list=evidence_list)

    def evidence_events_by_trace_id(self, trace_id: str) -> tuple[EvidenceEvent, ...]:
        return self._events_by_trace_id.get(trace_id, ())

    def _stored_chunks(self) -> tuple[StoredChunk, ...]:
        chunks = sorted(
            self._chunks_by_id.values(),
            key=lambda chunk: (chunk.document_id, chunk.position),
        )
        return tuple(
            StoredChunk(
                document=self._documents_by_id[chunk.document_id],
                chunk=chunk,
            )
            for chunk in chunks
            if chunk.document_id in self._documents_by_id
        )

    def _matches_filters(self, document: RagDocument, request: EvidenceSearchRequest) -> bool:
        if request.time_window is not None and not request.time_window.contains(document.published_at):
            return False
        if request.business_tags:
            requested_tags = set(normalize_tags(request.business_tags))
            document_tags = set(normalize_tags(document.business_tags))
            if not requested_tags.issubset(document_tags):
                return False
        return permission_tags_allowed(document.permission_tags, request.permission_tags)

    def _rank_chunks(
        self,
        chunks: tuple[StoredChunk, ...],
        query_text: str,
    ) -> tuple[tuple[StoredChunk, float], ...]:
        query_tokens = set(_tokens(query_text))
        ranked: list[tuple[StoredChunk, float]] = []
        for stored_chunk in chunks:
            chunk_tokens = set(_tokens(stored_chunk.chunk.text))
            if not query_tokens or not chunk_tokens:
                continue
            overlap = len(query_tokens & chunk_tokens)
            if overlap == 0:
                continue
            relevance_score = min(1.0, overlap / len(query_tokens))
            ranked.append((stored_chunk, round(relevance_score, 4)))

        return tuple(
            sorted(
                ranked,
                key=lambda item: (
                    item[1],
                    item[0].document.published_at,
                    -item[0].chunk.position,
                ),
                reverse=True,
            )
        )

    def _to_evidence_item(self, stored_chunk: StoredChunk, relevance_score: float) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=f"ev_{stored_chunk.chunk.chunk_id}",
            document_id=stored_chunk.document.document_id,
            chunk_id=stored_chunk.chunk.chunk_id,
            snippet=_snippet(stored_chunk.chunk.text),
            source=stored_chunk.document.source,
            published_at=stored_chunk.document.published_at,
            relevance_score=relevance_score,
        )


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower()))


def _snippet(text: str, max_length: int = 240) -> str:
    clean_text = " ".join(text.split())
    if len(clean_text) <= max_length:
        return clean_text
    return f"{clean_text[: max_length - 3].rstrip()}..."
