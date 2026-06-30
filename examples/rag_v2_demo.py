"""Runnable RAG v2 demo.

Run with:
    PYTHONPATH=src python examples/rag_v2_demo.py

The demo indexes one document, searches permitted evidence, builds a cited
answer, and prints the evidence events linked to the trace id.
"""

from __future__ import annotations

from datetime import datetime, timezone

from chatbi.rag_v2 import (
    EvidenceSearchRequest,
    IndexDocumentRequest,
    InMemoryRagService,
    RagAnsweringService,
)


def run_demo() -> str:
    rag_service = InMemoryRagService()
    rag_service.index_document(
        IndexDocumentRequest(
            document_id="doc_demo_release_note",
            source="demo-release-notes",
            title="Campaign pause release note",
            document_type="release_note",
            published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            business_tags=("revenue", "campaign"),
            permission_tags=("sales",),
            text=(
                "Revenue dropped after campaign spend paused. "
                "The pause reduced paid traffic and lowered new order volume."
            ),
        )
    )

    answering_service = RagAnsweringService(rag_service)
    answer = answering_service.answer(
        EvidenceSearchRequest(
            trace_id="trc_demo_rag_v2",
            query_text="Why did revenue drop after campaign spend paused?",
            time_window=None,
            business_tags=("revenue",),
            permission_tags=("sales",),
            limit=3,
        )
    )

    evidence_ids = ", ".join(
        evidence.evidence_id for evidence in answer.search_result.evidence_list
    )
    event_ids = ", ".join(event.event_id for event in answer.evidence_events)
    return (
        f"answer_text={answer.explanation.answer_text}\n"
        f"evidence_ids={evidence_ids}\n"
        f"event_ids={event_ids}\n"
    )


if __name__ == "__main__":
    print(run_demo())
