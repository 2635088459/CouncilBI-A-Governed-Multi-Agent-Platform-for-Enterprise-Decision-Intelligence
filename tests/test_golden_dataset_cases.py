"""Self-verification for golden_dataset/cases.json's real-business Golden
Dataset — mirrors test_retrieval_evaluation.py's TC-FV03-045 discipline:
every (question, expected_chunk_ids) label is checked by actually running
retrieve() against the same content migrations.py's
KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL seeds into production, not merely
asserted from unverified labels.
"""

from datetime import datetime, timezone
from typing import Callable

from chatbi.evaluation_cases import load_golden_dataset_cases
from chatbi.knowledge import DocumentChunk, InMemoryKnowledgeStore, KnowledgeDocument, RetrievalQuery
from chatbi.retrieval_evaluation import RetrievalEvaluator

# Mirrors migrations.py's KNOWLEDGE_RAG_SEED_SQL + KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL
# content exactly (source_id, title, doc_type, publish_time, chunk_text).
_SEEDED_DOCUMENTS = (
    (
        "rag_revenue_policy_2026",
        "Revenue metric policy and anomaly explanation",
        "policy",
        datetime(2026, 6, 25, tzinfo=timezone.utc),
        "Revenue is calculated from paid orders only. A month-over-month spike should be explained with campaign, refund, and region context.",
    ),
    (
        "doc_support_ops_june_2026",
        "Support operations weekly review",
        "weekly_report",
        datetime(2026, 6, 30, tzinfo=timezone.utc),
        "Support ticket volume increased for Governed Analytics after the enterprise workspace rollout. High-severity cases were prioritized and average resolution time improved in June.",
    ),
    (
        "doc_refund_policy_2026",
        "Refund policy and regional shipping delays",
        "policy",
        datetime(2026, 4, 10, tzinfo=timezone.utc),
        "Refunds are issued when an order is cancelled within 30 days or a shipping delay exceeds the regional SLA. A spike in refund requests should be cross-checked against regional carrier delays before being attributed to product quality.",
    ),
    (
        "doc_marketing_campaign_review_2026",
        "Marketing campaign spend and revenue attribution",
        "weekly_report",
        datetime(2026, 6, 5, tzinfo=timezone.utc),
        "Marketing campaign spend is tracked per campaign. When a campaign budget is paused mid-month, attributed revenue typically drops within the same reporting month, and this drop must not be confused with an organic demand decline.",
    ),
    (
        "doc_product_pricing_tier_2026",
        "Product pricing tier changes",
        "policy",
        datetime(2026, 5, 3, tzinfo=timezone.utc),
        "The Team pricing tier was reduced in price to widen the entry-level funnel. Any pricing tier change must be reflected in the product catalog before revenue-by-tier reports are regenerated.",
    ),
    (
        "doc_customer_churn_analysis_2026",
        "Customer churn analysis for the analytics tier",
        "weekly_report",
        datetime(2026, 3, 18, tzinfo=timezone.utc),
        "Customer churn increased for the analytics tier after a support SLA regression extended average ticket resolution time. Retention analysis must confirm whether unresolved tickets preceded cancellation.",
    ),
    (
        "doc_regional_sales_variance_2026",
        "Regional sales variance",
        "weekly_report",
        datetime(2026, 2, 14, tzinfo=timezone.utc),
        "Regional sales variance in the west region is driven primarily by carrier shipping delays, not by a change in regional demand or pricing.",
    ),
    (
        "doc_web_conversion_funnel_2026",
        "Web signup conversion funnel",
        "weekly_report",
        datetime(2026, 1, 20, tzinfo=timezone.utc),
        "Signup conversion improved after the web funnel redesign shortened the number of steps between account creation and first query. Onboarding completion is the canonical success marker for funnel reporting.",
    ),
    (
        "doc_sql_guardrail_policy_2026",
        "SQL guardrail and dangerous query policy",
        "policy",
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        "Any SQL statement beginning with DROP, DELETE, UPDATE, INSERT, ALTER, or TRUNCATE is blocked by the guardrail before execution. Analysts needing a destructive operation must route it through a reviewed migration, not the chat query path.",
    ),
    (
        "doc_data_governance_pii_policy_2026",
        "Data governance and PII masking policy",
        "policy",
        datetime(2026, 3, 2, tzinfo=timezone.utc),
        "Personally identifiable fields such as email and phone number must be masked in observability logs before they are persisted. Restricted field access is recorded for compliance review.",
    ),
    (
        "doc_incident_response_runbook_2026",
        "Incident response runbook",
        "weekly_report",
        datetime(2026, 5, 22, tzinfo=timezone.utc),
        "Incident response time improved after the on-call rotation was restructured for faster root-cause triage. P1 incidents must be escalated to the on-call engineer within 15 minutes of detection.",
    ),
    (
        "doc_eval_quality_gate_policy_2026",
        "Evaluation release gate policy",
        "policy",
        datetime(2026, 6, 12, tzinfo=timezone.utc),
        "A release is blocked from shipping when the overall evaluation score falls below 0.99 or the unsupported claim rate exceeds 2 percent. Retrieval Hit Rate and MRR are tracked as observability-only metrics and do not currently gate release.",
    ),
)


def _seed_store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    for source_id, title, doc_type, publish_time, chunk_text in _SEEDED_DOCUMENTS:
        store.save_document(
            KnowledgeDocument(source_id=source_id, title=title, doc_type=doc_type, publish_time=publish_time)
        )
        store.save_chunk(
            DocumentChunk(chunk_id=f"{source_id}_chunk_1", source_id=source_id, chunk_index=1, chunk_text=chunk_text)
        )
    return store


def _retrieve_fn_for(store: InMemoryKnowledgeStore) -> Callable[[str], tuple[str, ...]]:
    def retrieve_fn(question: str) -> tuple[str, ...]:
        result = store.retrieve(RetrievalQuery(question=question, requesting_user_id="u_eval", top_k=5))
        return tuple(
            f"{item.citation_anchor.split('#chunk-')[0]}_chunk_{item.citation_anchor.split('#chunk-')[1]}"
            for item in result.evidence_list
        )

    return retrieve_fn


def test_golden_dataset_cases_load_from_the_bundled_json_file() -> None:
    cases = load_golden_dataset_cases()

    assert len(cases) == 24
    assert len({case.case_id for case in cases}) == 24
    for case in cases:
        assert case.expected_chunk_ids


def test_golden_dataset_every_expected_chunk_id_exists_in_the_real_seeded_content() -> None:
    # NFR-FV03-011-style check: a dataset entry referencing a chunk_id that
    # doesn't exist in the real seed content must fail loudly, not silently
    # score as a permanent miss.
    known_chunk_ids = {f"{source_id}_chunk_1" for source_id, *_rest in _SEEDED_DOCUMENTS}

    for case in load_golden_dataset_cases():
        for expected_chunk_id in case.expected_chunk_ids:
            assert expected_chunk_id in known_chunk_ids, (
                f"{case.case_id} references unknown chunk_id {expected_chunk_id}"
            )


def test_golden_dataset_labels_are_verified_against_the_live_retrieve_pipeline() -> None:
    # Same discipline as test_retrieval_evaluation.py's TC-FV03-045: this is
    # what actually verifies every real-business label is correct, not
    # merely internally consistent with itself.
    store = _seed_store()
    cases = load_golden_dataset_cases()

    results = RetrievalEvaluator().evaluate(cases, _retrieve_fn_for(store))

    assert len(results) == len(cases)
    aggregate = RetrievalEvaluator().aggregate(results)
    assert aggregate["retrieval_hit_rate"] == 1.0
    assert aggregate["retrieval_mrr"] == 1.0
