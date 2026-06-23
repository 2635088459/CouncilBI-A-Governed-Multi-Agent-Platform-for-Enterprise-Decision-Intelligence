from datetime import datetime, timezone
from typing import Any, Mapping, cast

from chatbi.core.contracts import (
    AgentName,
    AgentStepStatus,
    ErrorCode,
    Locale,
    QueryHistoryStatus,
    QueryRequest,
    UserRole,
)
from chatbi.knowledge import DocumentChunk, InMemoryKnowledgeStore, KnowledgeDocument
from chatbi.orchestration.executor import PlanExecutor
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator
from chatbi.orchestration.tracing import AgentStepTracer, InMemoryAgentTraceLog


def make_request(
    question: str = "Show revenue trend.",
    role: UserRole = UserRole.BUSINESS_USER,
) -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question=question,
        locale=Locale.EN,
        role=role,
    )


def test_orchestrator_returns_structured_answer_for_valid_question() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request())

    assert answer.trace_id.startswith("trc_")
    assert answer.answer_text
    assert answer.sql_text.startswith("SELECT ")
    assert answer.table_result.columns == ("month", "revenue")


def test_orchestrator_saves_successful_request_to_history() -> None:
    orchestrator = SimpleOrchestrator()
    request = make_request("Show monthly revenue.")

    answer = orchestrator.answer(request)
    replayed = orchestrator.replay(answer.trace_id)

    assert replayed is not None
    assert replayed.request == request
    assert replayed.answer == answer
    assert replayed.failed_error_code is None
    assert replayed.status is QueryHistoryStatus.SUCCEEDED
    assert replayed.sql_text == answer.sql_text


def test_orchestrator_blocks_drop_table_before_execution() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request("DROP TABLE orders"))

    assert answer.confidence == 0.0
    assert answer.warnings
    assert answer.warnings[0].code is ErrorCode.SQL_DENY_STATEMENT
    assert answer.table_result.rows[0]["status"] == "blocked"


def test_orchestrator_saves_failed_request_to_history() -> None:
    orchestrator = SimpleOrchestrator()
    request = make_request("DROP TABLE orders")

    answer = orchestrator.answer(request)
    replayed = orchestrator.replay(answer.trace_id)

    assert replayed is not None
    assert replayed.request == request
    assert replayed.answer == answer
    assert replayed.failed_error_code is ErrorCode.SQL_DENY_STATEMENT
    assert replayed.status is QueryHistoryStatus.FAILED
    assert replayed.sql_text == answer.sql_text


def test_orchestrator_can_use_provided_trace_id() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request(), trace_id="trc_fixed")

    assert answer.trace_id == "trc_fixed"
    assert orchestrator.replay("trc_fixed") is not None


def test_orchestrator_uses_execution_plan_for_forecast_question() -> None:
    trace_log = InMemoryAgentTraceLog()
    plan_executor = PlanExecutor(tracer=AgentStepTracer(trace_log))
    orchestrator = SimpleOrchestrator(plan_executor=plan_executor)

    answer = orchestrator.answer(make_request("Predict revenue for next month."))
    events = trace_log.list_by_trace_id(answer.trace_id)

    terminal_agents = tuple(
        event.agent_name
        for event in events
        if event.status is AgentStepStatus.SUCCEEDED
    )

    assert terminal_agents == (AgentName.SQL, AgentName.ANALYTICS)
    assert answer.analytics_result is not None
    forecast_result = cast(Mapping[str, Any], answer.analytics_result["forecast_result"])
    assert forecast_result["model_used"] == "moving_average"
    assert len(forecast_result["forecast_series"]) == 3


def test_orchestrator_attaches_chart_spec_for_kpi_query() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request("Show monthly revenue trend."))

    assert answer.chart_spec is not None
    assert answer.chart_spec.chart_type.value == "line"
    assert answer.chart_spec.x_field == "month"
    assert answer.chart_spec.y_fields == ("revenue",)


def test_orchestrator_attaches_evidence_for_why_question() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request("Why did revenue drop?"))

    assert len(answer.evidence_list) == 1
    assert answer.evidence_list[0].source_id == "doc_revenue_release_notes"
    assert answer.evidence_list[0].citation_anchor == "doc_revenue_release_notes#p1"


def test_orchestrator_uses_knowledge_store_for_rag_evidence() -> None:
    knowledge_store = InMemoryKnowledgeStore()
    knowledge_store.save_document(
        KnowledgeDocument(
            source_id="doc_campaign",
            title="Campaign report",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
    )
    knowledge_store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_campaign_1",
            source_id="doc_campaign",
            chunk_index=1,
            chunk_text="Revenue dropped after campaign spend paused.",
        )
    )
    orchestrator = SimpleOrchestrator(knowledge_store=knowledge_store)

    answer = orchestrator.answer(make_request("Why did revenue drop?"))

    assert len(answer.evidence_list) == 1
    assert answer.evidence_list[0].source_id == "doc_campaign"
    assert answer.evidence_list[0].citation_anchor == "doc_campaign#chunk-1"
    assert answer.evidence_list[0].snippet == "Revenue dropped after campaign spend paused."
    assert answer.evidence_uncertainty is False
    assert answer.retrieval_stats is not None
    assert answer.retrieval_stats.selected_count == 1
    assert answer.retrieval_stats.filtered_count == 1


def test_orchestrator_filters_rag_evidence_by_request_role() -> None:
    knowledge_store = InMemoryKnowledgeStore()
    knowledge_store.save_document(
        KnowledgeDocument(
            source_id="doc_public_campaign",
            title="Campaign report",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
    )
    knowledge_store.save_document(
        KnowledgeDocument(
            source_id="doc_admin_incident",
            title="Executive incident report",
            doc_type="incident",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
            allowed_roles=("admin",),
        )
    )
    knowledge_store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_public_campaign",
            source_id="doc_public_campaign",
            chunk_index=1,
            chunk_text="Revenue dropped after campaign spend paused.",
        )
    )
    knowledge_store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_admin_incident",
            source_id="doc_admin_incident",
            chunk_index=1,
            chunk_text="Revenue dropped after a confidential executive incident.",
        )
    )
    orchestrator = SimpleOrchestrator(knowledge_store=knowledge_store)

    answer = orchestrator.answer(make_request("Why did revenue drop?"))

    assert tuple(item.source_id for item in answer.evidence_list) == ("doc_public_campaign",)


def test_orchestrator_allows_admin_rag_evidence_for_admin_request() -> None:
    knowledge_store = InMemoryKnowledgeStore()
    knowledge_store.save_document(
        KnowledgeDocument(
            source_id="doc_admin_incident",
            title="Executive incident report",
            doc_type="incident",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
            allowed_roles=("admin",),
        )
    )
    knowledge_store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_admin_incident",
            source_id="doc_admin_incident",
            chunk_index=1,
            chunk_text="Revenue dropped after a confidential executive incident.",
        )
    )
    orchestrator = SimpleOrchestrator(knowledge_store=knowledge_store)

    answer = orchestrator.answer(
        make_request("Why did revenue drop?", role=UserRole.ADMIN),
        trace_id="trc_admin_rag",
    )

    assert answer.trace_id == "trc_admin_rag"
    assert len(answer.evidence_list) == 1
    assert answer.evidence_list[0].source_id == "doc_admin_incident"


def test_orchestrator_marks_uncertainty_when_rag_retrieval_has_no_evidence() -> None:
    knowledge_store = InMemoryKnowledgeStore()
    knowledge_store.save_document(
        KnowledgeDocument(
            source_id="doc_report",
            title="Campaign report",
            doc_type="report",
            publish_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
            allowed_roles=("admin",),
        )
    )
    knowledge_store.save_chunk(
        DocumentChunk(
            chunk_id="chunk_report",
            source_id="doc_report",
            chunk_index=1,
            chunk_text="Revenue increased after campaign launch.",
        )
    )
    orchestrator = SimpleOrchestrator(knowledge_store=knowledge_store)

    answer = orchestrator.answer(make_request("Why did revenue drop?"))

    assert answer.evidence_list == ()
    assert answer.evidence_uncertainty is True
    assert answer.retrieval_stats is not None
    assert answer.retrieval_stats.filtered_count == 0
    assert answer.retrieval_stats.selected_count == 0
