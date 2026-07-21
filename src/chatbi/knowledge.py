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
from typing import Any, Callable, Mapping, Protocol
import logging
import re

from rank_bm25 import BM25Okapi

from chatbi.core.contracts import EvidenceItem, RetrievalStats
from chatbi.embedding_vector_rag import EmbeddingClient, EmbeddingRequest
from chatbi.knowledge_postgres_vector_source import VectorCandidateSource

_logger = logging.getLogger(__name__)


def _empty_metadata() -> Mapping[str, Any]:
    return {}


def _empty_tags() -> tuple[str, ...]:
    return ()


def _empty_roles() -> tuple[str, ...]:
    return ()


def _no_shared_visibility(document: "KnowledgeDocument") -> frozenset[str]:
    return frozenset()


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    source_id: str
    title: str
    doc_type: str
    publish_time: datetime
    tags: tuple[str, ...] = field(default_factory=_empty_tags)
    allowed_roles: tuple[str, ...] = field(default_factory=_empty_roles)
    owner_user_id: str | None = None


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
    requesting_user_id: str
    metric_context: str = ""
    conversation_context: str = ""
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

    def __init__(
        self,
        shared_visibility_resolver: Callable[[KnowledgeDocument], frozenset[str]] | None = None,
        embedding_client: EmbeddingClient | None = None,
        reranker: "CrossEncoderReranker | None" = None,
        vector_candidate_source: VectorCandidateSource | None = None,
    ) -> None:
        self._documents_by_source_id: dict[str, KnowledgeDocument] = {}
        self._chunks_by_chunk_id: dict[str, DocumentChunk] = {}
        self._embeddings_by_chunk_id: dict[str, ChunkEmbedding] = {}
        # FR-FV10-039: resolves which additional users may see an
        # owner-scoped document via an active file share grant (Spec
        # FV10.2). Until that spec is wired in, this defaults to "nobody",
        # which is a safe default for a private-by-default document.
        self._shared_visibility_resolver: Callable[[KnowledgeDocument], frozenset[str]] = (
            shared_visibility_resolver or _no_shared_visibility
        )
        # FR-FV03-014: real embeddings for the hybrid retrieval path (Spec
        # FV03.1). None keeps the deterministic hash-bucket text_embedding()
        # fallback every existing test already relies on.
        self._embedding_client = embedding_client
        # FR-FV03-021: cross-encoder rerank stage (Spec FV03.3). None keeps
        # today's behavior of dedupe/truncate over the hybrid-ranked order
        # with no second-pass re-scoring.
        self._reranker = reranker
        # FR-FV03-032: pluggable vector-candidate-generation step (Spec
        # FV03.5). None keeps today's in-memory linear cosine scan over
        # every filtered record — the only behavior every existing test
        # exercises.
        self._vector_candidate_source = vector_candidate_source

    def embed_text(
        self,
        text: str,
        embedding_client: EmbeddingClient | None = None,
        trace_id: str = "trc_knowledge_store_embed",
        org_id: str = "org_legacy",
    ) -> tuple[float, ...]:
        """FR-FV03-014: embed ``text`` with the given/constructor-level
        ``EmbeddingClient`` if one is available (method-level argument
        takes precedence), falling back to the deterministic hash-bucket
        ``text_embedding()`` otherwise.

        Every production call site that builds a ``ChunkEmbedding`` for this
        store (``ingest_document`` below, ``http._load_knowledge_store_from_db``,
        ``files.promotion``'s live-RAG indexing) goes through this method
        instead of calling ``text_embedding()`` directly, so one embedding
        provider switch governs all of them. ``trace_id``/``org_id`` default
        to this store's own ingestion-time identifiers rather than a live
        request's, since ingestion is not itself a traced chat request;
        callers with a real trace/org context may pass their own.
        """

        active_client = embedding_client or self._embedding_client
        if active_client is not None:
            response = active_client.embed(
                EmbeddingRequest(trace_id=trace_id, org_id=org_id, input_texts=(text,))
            )
            return response.vectors[0]
        return text_embedding(text)

    def set_shared_visibility_resolver(
        self, resolver: Callable[[KnowledgeDocument], frozenset[str]]
    ) -> None:
        """Rewire the FR-FV10-039 share-visibility hook after construction.

        Spec FV10.2's resolver needs the app's ``FileRepository``, which is
        not always available yet when this store is first built (see
        ``http._build_default_chatbi_application``). Callers wire the real
        resolver in once that repository exists.
        """

        self._shared_visibility_resolver = resolver

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

    def remove_document(self, source_id: str) -> None:
        """Remove a document and all of its chunks/embeddings (e.g. on demote)."""

        self._documents_by_source_id.pop(source_id, None)
        stale_chunk_ids = [
            chunk_id
            for chunk_id, chunk in self._chunks_by_chunk_id.items()
            if chunk.source_id == source_id
        ]
        for chunk_id in stale_chunk_ids:
            self._chunks_by_chunk_id.pop(chunk_id, None)
            self._embeddings_by_chunk_id.pop(chunk_id, None)

    def ingest_document(
        self,
        document: KnowledgeDocument,
        raw_text: str,
        chunk_size: int = 90,
        chunk_overlap: int = 15,
        embedding_client: EmbeddingClient | None = None,
    ) -> tuple[KnowledgeChunkRecord, ...]:
        """Clean, chunk, embed, and index one document.

        The unit is words instead of tokens because this project does not have
        a tokenizer dependency yet. The shape mirrors the real offline RAG
        flow: document -> clean -> chunk -> embed -> index.

        FR-FV03-014: ``embedding_client`` (or the one passed to this store's
        constructor) governs the vector each chunk is stored with; omitting
        both keeps the deterministic hash-bucket fallback.
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
                embedding_vector=self.embed_text(text, embedding_client),
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
        requesting_user_id: str = "",
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
            if not self._owner_can_read(document, requesting_user_id):
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
        requesting_user_id: str = "",
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
                requesting_user_id=requesting_user_id,
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
            requesting_user_id=query.requesting_user_id,
        )
        # FR-FV10-052/056: folding recent-turn context into the retrieval
        # text lets a follow-up like "why did that happen?" still match
        # documents about the actual subject from the prior turn, with no
        # separate rewrite step.
        #
        # Computed once here — via embed_text(), so it uses this store's
        # real configured EmbeddingClient rather than always falling back
        # to the deterministic hash — and passed to both the vector
        # narrowing step and hybrid ranking below, so they agree on both
        # the embedding provider and the text basis instead of each
        # independently recomputing their own (previously divergent)
        # fallback.
        query_text = f"{query.question} {query.metric_context} {query.conversation_context}".strip()
        query_embedding = query.query_embedding or self.embed_text(query_text)
        # FR-FV03-032: narrows toward (never widens beyond) the permission
        # filtering list_chunk_records() already applied above.
        filtered_records = self._narrow_by_vector_candidates(filtered_records, query, query_embedding)
        ranked_records = self._rank_records(filtered_records, query, query_text, query_embedding)
        narrowed_records = ranked_records[: max(query.top_k * 2, query.top_k)]
        # FR-FV03-021: genuine second-pass re-scoring of the narrowed
        # candidate window, bounded regardless of corpus size — reranking
        # never runs on more than max(top_k * 2, top_k) chunks.
        reranked_records, did_rerank = rerank(query.question, narrowed_records, self._reranker)
        selected_records = self._dedupe_adjacent_chunks(reranked_records)
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
                # FR-FV03-022: reflects candidates that actually passed
                # through the cross-encoder — did_rerank is False both when
                # no reranker is configured and when a configured one
                # failed and rerank() fell back, so a broken reranker no
                # longer misreports as a successful one.
                reranked_count=len(narrowed_records) if did_rerank else 0,
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

    def _owner_can_read(self, document: KnowledgeDocument, requesting_user_id: str) -> bool:
        """FR-FV10-038/039: baseline docs stay open; owned docs are private.

        ``owner_user_id is None`` marks baseline/system knowledge (seeded
        documents), which this spec leaves untouched — visibility there is
        governed entirely by ``allowed_roles``, not by who is asking.
        """

        if document.owner_user_id is None:
            return True
        if requesting_user_id and requesting_user_id == document.owner_user_id:
            return True
        return bool(requesting_user_id) and requesting_user_id in self._shared_visibility(document)

    def _shared_visibility(self, document: KnowledgeDocument) -> frozenset[str]:
        return self._shared_visibility_resolver(document)

    def _narrow_by_vector_candidates(
        self,
        filtered_records: tuple[KnowledgeChunkRecord, ...],
        query: RetrievalQuery,
        query_embedding: tuple[float, ...],
    ) -> tuple[KnowledgeChunkRecord, ...]:
        """FR-FV03-032/034 (Spec FV03.5): intersects, never replaces,
        ``list_chunk_records()``'s own permission filtering — the source's
        known gap (no shared-visibility support, see
        ``PostgresKnowledgeVectorSource``'s own docstring) means it is only
        ever a narrowing prefilter, not the authority. Any error narrows to
        nothing extra (falls back to ``filtered_records`` unchanged) rather
        than failing the request, the same "degrade, don't crash" posture
        ``rerank()`` already established for Spec FV03.3.

        ``query_embedding`` is computed once by the caller (``retrieve()``),
        via ``embed_text()``, so this narrowing step searches the *same*
        embedding space ``knowledge.doc_embeddings`` was populated in —
        never a hash-bucket fallback compared against real document
        vectors.
        """

        if self._vector_candidate_source is None:
            return filtered_records
        try:
            candidates = self._vector_candidate_source.top_chunk_ids(
                query_vector=query_embedding,
                requesting_user_id=query.requesting_user_id,
                user_role=query.user_role,
                doc_type=query.doc_type,
                doc_types=query.doc_types,
                limit=max(query.top_k * 4, 20),
            )
        except Exception:
            _logger.warning(
                "vector_candidate_source.top_chunk_ids() failed; falling back to the"
                " full permission-filtered candidate set for this request.",
                exc_info=True,
            )
            return filtered_records
        candidate_chunk_ids = {chunk_id for chunk_id, _distance in candidates}
        return tuple(
            record for record in filtered_records if record.chunk.chunk_id in candidate_chunk_ids
        )

    def _rank_records(
        self,
        records: tuple[KnowledgeChunkRecord, ...],
        query: RetrievalQuery,
        query_text: str,
        query_embedding: tuple[float, ...],
    ) -> tuple[KnowledgeChunkRecord, ...]:
        scored_records: list[KnowledgeChunkRecord] = []

        # FR-FV03-018: BM25 built fresh over exactly this request's already
        # permission-filtered candidate set — no persistent/global index, so
        # no document outside `records` can influence these IDF statistics.
        keyword_scores = (
            Bm25CandidateScorer(records).scores(cjk_and_ascii_tokens(query_text))
            if records
            else ()
        )

        for record, keyword_score in zip(records, keyword_scores):
            vector_score = cosine_similarity(
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
        """Merge adjacent same-document chunks, preserving ``records``' own
        incoming order (by the earliest input position among each merged
        record's constituent chunks) rather than re-deriving an order from
        ``relevance_score``.

        FR-FV03-021: this matters once a cross-encoder reranker has already
        re-sorted ``records`` — re-sorting by ``relevance_score`` here would
        silently discard that rerank order and fall back to the pre-rerank
        hybrid score, since ``rerank()`` reorders records without rewriting
        their ``relevance_score`` field. When no reranker is configured,
        ``records`` already arrives in ``_rank_records()``'s relevance-sorted
        order, so preserving input order reproduces the same output this
        method produced before FR-FV03-021.
        """

        if not records:
            return ()

        order_index = {id(record): index for index, record in enumerate(records)}
        records_by_doc: dict[str, list[KnowledgeChunkRecord]] = {}
        for record in records:
            records_by_doc.setdefault(record.document.source_id, []).append(record)

        merged_with_order: list[tuple[int, KnowledgeChunkRecord]] = []
        for doc_records in records_by_doc.values():
            sorted_records = sorted(doc_records, key=lambda item: item.chunk.chunk_index)
            current = sorted_records[0]
            current_min_index = order_index[id(current)]
            for next_record in sorted_records[1:]:
                if next_record.chunk.chunk_index == current.chunk.chunk_index + 1:
                    current_min_index = min(current_min_index, order_index[id(next_record)])
                    current = self._merge_records(current, next_record)
                    continue
                merged_with_order.append((current_min_index, current))
                current = next_record
                current_min_index = order_index[id(current)]
            merged_with_order.append((current_min_index, current))

        merged_with_order.sort(key=lambda item: item[0])
        return tuple(record for _, record in merged_with_order)

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
    for token in text_tokens(text):
        bucket = sum(ord(character) for character in token) % dimensions
        vector[bucket] += 1.0
    magnitude = sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return tuple(vector)
    return tuple(value / magnitude for value in vector)


def text_tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower()))


def keyword_overlap_score(query_tokens: tuple[str, ...], chunk_tokens: tuple[str, ...]) -> float:
    """Query-token-coverage ratio still used by FileScopedRetriever (Spec
    FV10.6) against user-uploaded-file candidates — out of Spec FV03.2's
    scope, which only replaces InMemoryKnowledgeStore._rank_records()'s own
    keyword term with BM25 (see cjk_and_ascii_tokens/Bm25CandidateScorer
    below)."""

    if not query_tokens or not chunk_tokens:
        return 0.0

    query_set = set(query_tokens)
    chunk_set = set(chunk_tokens)
    return len(query_set & chunk_set) / len(query_set)


def cjk_and_ascii_tokens(text: str) -> tuple[str, ...]:
    """FR-FV03-019: BM25 tokenization — ASCII word tokens (matching
    ``text_tokens()``) plus CJK unigrams, so Chinese-language chunks and
    questions are not silently dropped from keyword scoring the way they
    are by the ASCII-only ``[a-z0-9]+`` pattern ``text_tokens()`` uses for
    the (unrelated) deterministic hash-bucket embedding.
    """

    ascii_tokens = re.findall(r"[a-z0-9]+", text.lower())
    cjk_tokens = re.findall(r"[一-鿿]", text)
    return tuple(ascii_tokens) + tuple(cjk_tokens)


def normalize_scores(raw_scores: tuple[float, ...]) -> tuple[float, ...]:
    """FR-FV03-020: min-max normalize BM25's unbounded raw scores into a
    range comparable to the [0, 1]-bounded cosine_similarity term.

    An all-equal input (including a single-candidate corpus, where BM25
    degenerates to identical scores) maps to a neutral 0.5, not 0.0: with
    only one document in the corpus, standard Okapi BM25's IDF term is
    itself corpus-size-dependent and commonly negative even for a genuine
    keyword match (a term appearing in 100% of a 1-document corpus reads
    as "common", not "rare") — so the raw score's sign is not a reliable
    signal of relevance here, and forcing it to 0.0 previously suppressed
    real single-candidate matches outright. 0.5 lets keyword scoring defer
    to the vector/source-weight terms in the fusion formula in this
    genuinely-indeterminate case, rather than actively arguing against
    relevance the way 0.0 did.
    """

    if not raw_scores:
        return raw_scores
    lo, hi = min(raw_scores), max(raw_scores)
    if hi == lo:
        return tuple(0.5 for _ in raw_scores)
    return tuple((score - lo) / (hi - lo) for score in raw_scores)


class Bm25CandidateScorer:
    """FR-FV03-018: BM25 keyword scoring, built fresh per request over
    exactly the caller's already permission-filtered candidate set — never
    a persistent or pre-built index, so this request's IDF statistics
    cannot be influenced by, or leak information about, any document
    outside that set.
    """

    def __init__(self, records: tuple[KnowledgeChunkRecord, ...]) -> None:
        self._records = records
        corpus = [cjk_and_ascii_tokens(record.chunk.chunk_text) for record in records]
        self._bm25 = BM25Okapi(corpus)

    def scores(self, query_tokens: tuple[str, ...]) -> tuple[float, ...]:
        # rank_bm25 ships no type stubs; get_scores()'s return type is
        # untyped from pyright's perspective, hence the blanket ignore.
        raw_scores_array = self._bm25.get_scores(list(query_tokens))  # type: ignore
        raw_scores = tuple(float(score) for score in raw_scores_array)  # type: ignore
        return normalize_scores(raw_scores)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
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


class CrossEncoderReranker(Protocol):
    """FR-FV03-021: a second-pass re-scorer that reads (question, chunk)
    pairs jointly, unlike the independently-computed keyword/vector scores
    _rank_records() fuses beforehand."""

    def score(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]:
        ...


class BgeCrossEncoderReranker:
    """FR-FV03-021 / NFR-FV03-009: loads BAAI/bge-reranker-base once,
    lazily, at first use — not per request. Requires the optional
    ``rerank`` extra (``sentence-transformers``); importing this class
    without it installed only fails once ``score()`` is actually called,
    not at import time.
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        self._model_name = model_name
        self._model: Any = None

    def score(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]:
        if self._model is None:
            from sentence_transformers import CrossEncoder  # type: ignore

            self._model = CrossEncoder(self._model_name)
        raw_scores = self._model.predict(list(pairs))  # type: ignore
        return tuple(float(score) for score in raw_scores)  # type: ignore


def rerank(
    question: str,
    candidates: tuple[KnowledgeChunkRecord, ...],
    reranker: CrossEncoderReranker | None,
) -> tuple[tuple[KnowledgeChunkRecord, ...], bool]:
    """FR-FV03-023: on reranker absence or any error, returns candidates
    unchanged (the pre-rerank hybrid ordering) rather than propagating —
    evidence with slightly worse ranking is strictly better than a failed
    request, the same "degrade, don't crash" posture this project's
    orchestrator already applies to non-critical agent failures.

    Returns ``(records, did_rerank)`` — ``did_rerank`` is ``True`` only when
    a reranker was configured AND actually scored the candidates, so a
    caller (``retrieve()``'s ``RetrievalStats.reranked_count``) can tell a
    genuine rerank pass apart from a silent fallback, instead of inferring
    success from "a reranker happened to be configured."
    """

    if reranker is None or not candidates:
        return candidates, False
    try:
        pairs = tuple((question, record.chunk.chunk_text) for record in candidates)
        scores = reranker.score(pairs)
    except Exception:
        _logger.warning(
            "Cross-encoder reranker failed; falling back to the pre-rerank hybrid ordering.",
            exc_info=True,
        )
        return candidates, False
    ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)
    return tuple(record for record, _ in ranked), True
