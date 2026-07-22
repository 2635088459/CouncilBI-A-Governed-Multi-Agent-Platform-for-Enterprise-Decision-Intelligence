"""Mines real chat-query questions that actually reached the RAG path with
nonzero evidence, as candidate material for growing
golden_dataset/cases.json with real production questions — the "human
review process" Spec FV03.4 §5.2/§9 describes this feeds into, not
replaces. A question that never triggered RAG evidence (a pure-SQL
question, for instance) was never a retrieval candidate to begin with, so
it is excluded rather than surfaced as noise for the reviewer to filter out
by hand.

Works against either backing store transparently (ObservabilityLogStore /
ObservabilityStore protocols — observability_logs.py / observability.py):
the in-memory ones (local runtime, tests), which only see the current
process's uptime, or the Postgres-backed ones (observability_postgres.py,
Spec 4.7), which persist across restarts and are what makes mining a real
deployment's full question history — not just whatever it saw since its
last restart — actually possible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from chatbi.knowledge import InMemoryKnowledgeStore, RetrievalQuery
from chatbi.observability import ObservabilityStore, TraceSpanName
from chatbi.observability_logs import ObservabilityLogStore


@dataclass(frozen=True, slots=True)
class CandidateChunk:
    """One of retrieve()'s own top-K results for a candidate question — a
    labeling shortlist entry, not a suggested label."""

    chunk_id: str
    snippet: str
    relevance_score: float


@dataclass(frozen=True, slots=True)
class RetrievalLabelingCandidate:
    """One real question awaiting human review before it may become a
    Golden Dataset case. A human reviewer still decides which (if any)
    candidate_chunks entry is actually correct — this module surfaces
    candidates, it does not label them."""

    trace_id: str
    question: str
    candidate_chunks: tuple[CandidateChunk, ...]


def mine_retrieval_labeling_candidates(
    log_store: ObservabilityLogStore,
    trace_store: ObservabilityStore,
    knowledge_store: InMemoryKnowledgeStore,
    requesting_user_id: str = "golden_dataset_mining",
    top_k: int = 5,
) -> tuple[RetrievalLabelingCandidate, ...]:
    """FR-FV03-025 follow-up (Spec 4.6 §3.4's continuation): real questions
    that triggered a `rag_retrieved` trace span with `evidence_count > 0`
    are the representative population to draw new Golden Dataset cases
    from. Deduplicates by normalized question text — repeated identical
    questions across many requests are not separate candidates.
    """

    trace_ids_with_evidence = {
        span.trace_id
        for span in trace_store.list_all()
        if span.span_name is TraceSpanName.RAG_RETRIEVED
        and int(span.attributes.get("evidence_count", 0) or 0) > 0
    }

    seen_questions: set[str] = set()
    candidates: list[RetrievalLabelingCandidate] = []
    for record in log_store.list_all():
        if record.trace_id not in trace_ids_with_evidence:
            continue
        question = record.attributes.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        normalized_question = question.strip().lower()
        if normalized_question in seen_questions:
            continue
        seen_questions.add(normalized_question)

        result = knowledge_store.retrieve(
            RetrievalQuery(question=question, requesting_user_id=requesting_user_id, top_k=top_k)
        )
        candidate_chunks = tuple(
            CandidateChunk(
                chunk_id=(
                    f"{item.citation_anchor.split('#chunk-')[0]}"
                    f"_chunk_{item.citation_anchor.split('#chunk-')[1]}"
                ),
                snippet=item.snippet,
                relevance_score=item.relevance_score,
            )
            for item in result.evidence_list
        )
        candidates.append(
            RetrievalLabelingCandidate(
                trace_id=record.trace_id,
                question=question,
                candidate_chunks=candidate_chunks,
            )
        )
    return tuple(candidates)


def export_labeling_candidates(candidates: tuple[RetrievalLabelingCandidate, ...], path: Path) -> None:
    """Writes a human-reviewable worksheet: one entry per candidate
    question, with retrieve()'s own top-K shortlist already attached, so a
    reviewer only has to pick (or reject) rather than search from scratch —
    the same model-assisted labeling process used to author the initial 24
    real-business cases in golden_dataset/cases.json (Spec 4.6 §3.4).
    `reviewer_expected_chunk_ids` is left empty for the reviewer to fill in;
    a confirmed candidate graduates into golden_dataset/cases.json as its
    own case_id/question/expected_chunk_ids entry.
    """

    payload = [
        {
            "trace_id": candidate.trace_id,
            "question": candidate.question,
            "candidate_chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "snippet": chunk.snippet,
                    "relevance_score": chunk.relevance_score,
                }
                for chunk in candidate.candidate_chunks
            ],
            "reviewer_expected_chunk_ids": [],
        }
        for candidate in candidates
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
