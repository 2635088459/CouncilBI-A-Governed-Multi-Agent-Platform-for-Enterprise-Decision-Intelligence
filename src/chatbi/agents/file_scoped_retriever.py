"""FileScopedRetriever: RAG evidence scoped to one request's own file_ids.

Spec FV10.6 FR-FV10-065/069. This is deliberately not a second knowledge
store: it reuses ``chatbi.knowledge``'s existing keyword+vector scoring
functions against a narrower candidate set — the already-chunked,
already-embedded content of exactly the unstructured files a request
attached, read via ``FileVectorSource.chunks_with_vectors_for_file()``. No
promotion step, no admin approval, no org-wide visibility: the caller MUST
only pass ``file_ids`` that ownership/readiness screening
(``_validate_chat_query_file_ids`` in http.py) has already approved for the
requesting user (FR-FV10-069) — this class performs no authorization check
of its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.core.contracts import EvidenceItem
from chatbi.embedding_vector_rag import EmbeddingClient, EmbeddingRequest
from chatbi.files.parser_unstructured import TextChunk
from chatbi.files.repository import FileRepository
from chatbi.files.worker import FileVectorSource
from chatbi.knowledge import cosine_similarity, keyword_overlap_score, text_embedding, text_tokens


@dataclass(frozen=True, slots=True)
class FileScopedRetriever:
    vector_source: FileVectorSource
    repository: FileRepository
    # Code-review fix: the chunk vectors chunks_with_vectors_for_file()
    # returns come from FileProcessingWorker's real, configured
    # EmbeddingClient (see files/worker.py's own module docstring) — the
    # query side must be embedded with the *same* client, or comparing a
    # deterministic hash-bucket query vector against real document vectors
    # produces a meaningless cosine similarity. None keeps the
    # deterministic text_embedding() fallback for offline tests.
    embedding_client: EmbeddingClient | None = None

    def retrieve(
        self, *, question: str, file_ids: tuple[str, ...], top_k: int = 5
    ) -> tuple[EvidenceItem, ...]:
        """Returns () when every file_id's chunk lookup is empty — FR-FV10-070
        ("no content available for search") is the caller's job to detect
        and surface distinctly; this method does not distinguish that case
        from "searched, found nothing relevant" in its return value alone.
        """

        candidates: list[tuple[str, TextChunk, tuple[float, ...]]] = []
        for file_id in file_ids:
            for chunk, vector in self.vector_source.chunks_with_vectors_for_file(file_id):
                candidates.append((file_id, chunk, vector))

        ranked = self._rank(question, candidates)
        return tuple(
            self._evidence_item(file_id, chunk, score) for file_id, chunk, score in ranked[:top_k]
        )

    def _rank(
        self,
        question: str,
        candidates: list[tuple[str, TextChunk, tuple[float, ...]]],
    ) -> list[tuple[str, TextChunk, float]]:
        # Same two scoring functions chatbi.knowledge's InMemoryKnowledgeStore
        # uses (_rank_records) — no source_weight term here, since a raw
        # uploaded-file chunk has no doc_type to weight by.
        query_tokens = text_tokens(question)
        query_embedding = (
            self.embedding_client.embed(
                EmbeddingRequest(
                    trace_id="trc_file_scoped_retrieve",
                    org_id="org_legacy",
                    input_texts=(question,),
                )
            ).vectors[0]
            if self.embedding_client is not None
            else text_embedding(question)
        )

        scored: list[tuple[str, TextChunk, float]] = []
        for file_id, chunk, vector in candidates:
            keyword_score = keyword_overlap_score(query_tokens, text_tokens(chunk.text))
            vector_score = cosine_similarity(query_embedding, vector)
            relevance_score = round((keyword_score * 0.60) + (vector_score * 0.40), 4)
            if relevance_score <= 0:
                continue
            scored.append((file_id, chunk, relevance_score))

        return sorted(scored, key=lambda item: (item[2], -item[1].chunk_index), reverse=True)

    def _evidence_item(self, file_id: str, chunk: TextChunk, relevance_score: float) -> EvidenceItem:
        file = self.repository.get(file_id)
        title = file.original_name if file is not None else file_id
        return EvidenceItem(
            source_id=file_id,
            title=title,
            citation_anchor=f"{file_id}#chunk-{chunk.chunk_index}",
            snippet=chunk.text,
            relevance_score=min(1.0, max(0.0, relevance_score)),
        )
