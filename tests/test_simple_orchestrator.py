from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, cast

from chatbi.analytics import AnalyticsService
from chatbi.analytics_repository import InMemoryAnalyticsRepository
from chatbi.core.contracts import (
    AgentName,
    AgentStepStatus,
    ErrorCode,
    GuardrailDecision,
    Locale,
    QueryAnswer,
    QueryHistoryStatus,
    QueryRequest,
    TableResult,
    UserRole,
)
from chatbi.governance import ReadOnlyQueryResult, ReadOnlyQueryStatus
from chatbi.knowledge import DocumentChunk, InMemoryKnowledgeStore, KnowledgeDocument
from chatbi.llm import LLMRequest, LLMResponse
from chatbi.orchestration.answer_verification import AnswerAssemblyVerifier
from chatbi.orchestration.executor import AgentRunner, AgentRunResult, PlanExecutionResult, PlanExecutor
from chatbi.orchestration.routing import ExecutionPlan
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator
from chatbi.orchestration.state import InMemoryOrchestrationStateStore, RequestStateStage
from chatbi.orchestration.tracing import AgentStepTracer, InMemoryAgentTraceLog
from chatbi.trace_events import TraceEventStatus


class VerifierFailedExecutor(PlanExecutor):
    def execute(
        self,
        trace_id: str,
        plan: ExecutionPlan,
        runners: Mapping[AgentName, AgentRunner],
    ) -> PlanExecutionResult:
        return PlanExecutionResult(
            outputs={
                AgentName.SQL: AgentRunResult(
                    payload={"safe_sql": "SELECT month, revenue FROM revenue_by_month LIMIT 100"},
                    confidence=0.9,
                ),
                AgentName.VERIFIER: AgentRunResult(
                    payload={
                        "verified": False,
                        "reason": "Required fields were checked.",
                        "findings": ("Required answer field(s) missing: table_result.",),
                    },
                    confidence=0.5,
                ),
            },
            confidence=0.65,
        )


class FakeReadOnlyQueryExecutor:
    def __init__(self, result: ReadOnlyQueryResult) -> None:
        self.result = result
        self.calls: list[tuple[str | None, str]] = []

    def execute(self, database_url: str | None, sql_text: str) -> ReadOnlyQueryResult:
        self.calls.append((database_url, sql_text))
        return self.result


class MissingSqlAnswerVerifier(AnswerAssemblyVerifier):
    def verify(self, answer: QueryAnswer) -> QueryAnswer:
        return super().verify(replace(answer, sql_text=""))


class RecordingLLMClient:
    def __init__(self, response_text: str = "Synthesized from governed context.") -> None:
        self.response_text = response_text
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            text=self.response_text,
            model_name="fake-model",
            provider="fake",
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
            estimated_cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )


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


def test_orchestrator_writes_guardrail_audit_for_allowed_sql() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request(), trace_id="trc_guardrail_audit_allow")
    audit_record = orchestrator.guardrail_audit_log.get(answer.trace_id)

    assert audit_record is not None
    assert audit_record.trace_id == "trc_guardrail_audit_allow"
    assert audit_record.user_id == "u_001"
    assert audit_record.role is UserRole.BUSINESS_USER
    assert audit_record.decision is GuardrailDecision.ALLOW
    assert audit_record.original_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert audit_record.safe_sql is not None
    assert audit_record.safe_sql.startswith("SELECT ")


def test_orchestrator_answers_2012_highest_revenue_with_data_provenance() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request("Which month had the highest revenue in 2012?"))

    assert answer.sql_text == (
        "SELECT month, revenue FROM revenue_by_month "
        "WHERE month LIKE '2012-%' ORDER BY revenue DESC LIMIT 100"
    )
    assert answer.answer_text == "Highest revenue month was 2012-12 with revenue 1625.0."
    assert answer.table_result.rows[0] == {"month": "2012-01", "revenue": 940.0}
    assert answer.table_result.rows[-1] == {"month": "2012-12", "revenue": 1625.0}
    assert len(answer.evidence_list) == 1
    assert answer.evidence_list[0].source_id == "dataset_revenue_monthly_2012"
    assert answer.evidence_list[0].citation_anchor == "business.revenue_by_month#2012"


def test_orchestrator_answers_2011_highest_revenue_without_cross_year_leakage() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request("Which month had the highest revenue in 2011?"))

    assert answer.sql_text == (
        "SELECT month, revenue FROM revenue_by_month "
        "WHERE month LIKE '2011-%' ORDER BY revenue DESC LIMIT 100"
    )
    assert answer.answer_text == "Highest revenue month was 2011-12 with revenue 1253.0."
    assert len(answer.table_result.rows) == 12
    assert {str(row["month"])[:4] for row in answer.table_result.rows} == {"2011"}
    assert not any(str(row["month"]).startswith(("2012", "2026")) for row in answer.table_result.rows)
    assert answer.evidence_list[0].source_id == "dataset_revenue_monthly_2011"
    assert answer.evidence_list[0].citation_anchor == "business.revenue_by_month#2011"


def test_orchestrator_does_not_attach_support_evidence_to_revenue_rows_for_mixed_question() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(
        make_request(
            "Which month had the highest revenue in 2011? "
            "Show revenue trend by month. Which support ticket area needs attention?"
        )
    )

    assert answer.table_result.columns == ("month", "revenue")
    assert "Highest revenue month was 2011-12" in answer.answer_text
    assert "Support ticket volume" not in answer.answer_text
    assert tuple(evidence.source_id for evidence in answer.evidence_list) == (
        "dataset_revenue_monthly_2011",
    )


def test_orchestrator_answers_support_ticket_question_from_non_revenue_dataset() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request("Which support ticket area needs attention?"))

    assert answer.sql_text == (
        "SELECT month, product, severity, ticket_count, avg_resolution_hours "
        "FROM support_ticket_summary ORDER BY ticket_count DESC LIMIT 100"
    )
    assert answer.table_result.columns == (
        "month",
        "product",
        "severity",
        "ticket_count",
        "avg_resolution_hours",
    )
    assert answer.table_result.rows[0]["product"] == "Governed Analytics"
    assert "Support ticket volume is led by Governed Analytics high tickets" in answer.answer_text
    assert tuple(evidence.source_id for evidence in answer.evidence_list) == (
        "doc_support_ops_june_2026",
        "dataset_support_ticket_summary",
    )


def test_orchestrator_explain_query_uses_rag_evidence_in_synthesis() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request("Explain why revenue changed in H1 2026."))

    assert answer.evidence_list
    assert answer.evidence_list[0].citation_anchor == "doc_revenue_release_notes#p1"
    assert answer.answer_text == (
        "Revenue changed based on evidence from doc_revenue_release_notes#p1: "
        "Revenue changes were linked to campaign timing."
    )


def test_orchestrator_rejects_unsupported_question_before_default_revenue_sql() -> None:
    llm_client = RecordingLLMClient("This should not be called.")
    orchestrator = SimpleOrchestrator(llm_client=llm_client)

    answer = orchestrator.answer(make_request("hello"), trace_id="trc_unsupported_hello")

    assert answer.sql_text == ""
    assert answer.table_result.rows == (
        {
            "status": "blocked",
            "reason": (
                "I can answer governed business questions about revenue, orders, "
                "refunds, support tickets, trends, forecasts, anomalies, or documented explanations."
            ),
        },
    )
    assert answer.warnings[0].code is ErrorCode.UNSUPPORTED_QUESTION
    assert llm_client.requests == []


def test_orchestrator_passes_sql_rows_and_evidence_to_answer_synthesis_llm() -> None:
    llm_client = RecordingLLMClient("LLM used rows and evidence.")
    orchestrator = SimpleOrchestrator(llm_client=llm_client)

    answer = orchestrator.answer(
        make_request("Which support ticket area needs attention?", role=UserRole.ANALYST),
        trace_id="trc_answer_synthesis_context",
    )

    assert answer.answer_text == "LLM used rows and evidence."
    synthesis_requests = [
        request for request in llm_client.requests if request.task_type == "answer_synthesis"
    ]
    assert len(synthesis_requests) == 1
    prompt = synthesis_requests[0].messages[-1]["content"]
    assert "support_ticket_summary" in prompt
    assert "Governed Analytics" in prompt
    assert "ticket_count" in prompt
    assert "doc_support_ops_june_2026#p1" in prompt


def test_orchestrator_writes_spec_trace_events_for_success() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request(), trace_id="trc_orchestrator_trace_success")
    events = orchestrator.trace_event_store.list_by_trace_id(answer.trace_id)

    assert tuple(event.status for event in events) == (
        TraceEventStatus.STARTED,
        TraceEventStatus.SUCCEEDED,
    )
    assert events[0].service == "orchestrator"
    assert events[0].span_name == "orchestration"
    assert events[1].latency_ms is not None
    assert events[1].latency_ms >= 0


def test_orchestrator_writes_degraded_spec_trace_event_for_denied_sql() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(
        make_request("DROP TABLE orders"),
        trace_id="trc_orchestrator_trace_degraded",
    )
    events = orchestrator.trace_event_store.list_by_trace_id(answer.trace_id)

    assert events[-1].status is TraceEventStatus.DEGRADED
    assert events[-1].service == "orchestrator"


def test_orchestrator_writes_guardrail_audit_for_denied_sql() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(
        make_request("DROP TABLE orders"),
        trace_id="trc_guardrail_audit_deny",
    )
    audit_record = orchestrator.guardrail_audit_log.get(answer.trace_id)

    assert audit_record is not None
    assert audit_record.trace_id == "trc_guardrail_audit_deny"
    assert audit_record.decision is GuardrailDecision.DENY
    assert audit_record.original_sql == "DROP TABLE orders"
    assert audit_record.error_code is ErrorCode.SQL_DENY_STATEMENT
    assert audit_record.message == "Only SELECT statements are allowed."


def test_orchestrator_uses_readonly_query_executor_table_result_when_configured() -> None:
    readonly_result = ReadOnlyQueryResult(
        status=ReadOnlyQueryStatus.SUCCEEDED,
        table_result=TableResult(
            columns=("month", "revenue"),
            rows=({"month": "2026-07", "revenue": 1400.0},),
        ),
    )
    readonly_executor = FakeReadOnlyQueryExecutor(readonly_result)
    orchestrator = SimpleOrchestrator(
        readonly_query_executor=readonly_executor,
        readonly_database_url="postgresql://chatbi_readonly:test@db:5432/chatbi",
    )

    answer = orchestrator.answer(make_request())

    assert answer.table_result == readonly_result.table_result
    assert readonly_executor.calls == [
        (
            "postgresql://chatbi_readonly:test@db:5432/chatbi",
            "SELECT month, revenue FROM revenue_by_month LIMIT 100",
        )
    ]
    assert answer.warnings == ()


def test_orchestrator_falls_back_when_readonly_query_executor_fails() -> None:
    readonly_executor = FakeReadOnlyQueryExecutor(
        ReadOnlyQueryResult(
            status=ReadOnlyQueryStatus.EXECUTION_FAILED,
            message="Read-only query execution failed.",
        )
    )
    orchestrator = SimpleOrchestrator(
        readonly_query_executor=readonly_executor,
        readonly_database_url="postgresql://chatbi_readonly:test@db:5432/chatbi",
    )

    answer = orchestrator.answer(make_request())

    assert answer.table_result.columns == ("month", "revenue")
    assert answer.table_result.rows[0] == {"month": "2026-01", "revenue": 1000.0}
    assert answer.warnings[-1].code is ErrorCode.INTERNAL_ERROR
    assert answer.warnings[-1].message == "Read-only query execution failed."


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


def test_orchestrator_saves_request_state_by_trace_id() -> None:
    state_store = InMemoryOrchestrationStateStore()
    plan_executor = PlanExecutor(state_store=state_store)
    orchestrator = SimpleOrchestrator(plan_executor=plan_executor)

    answer = orchestrator.answer(make_request("What was total revenue last month?"))
    state = state_store.get_request_state(answer.trace_id)

    assert state is not None
    assert state.stage is RequestStateStage.SUCCEEDED
    assert state.input_summary["session_id"] == "s_001"
    assert state.input_summary["role"] == "business_user"
    assert state.output_summary is not None
    assert state.output_summary["confidence"] == answer.confidence
    assert state.latency_ms is not None
    assert state.latency_ms >= 0


def test_orchestrator_adds_warning_when_verifier_rejects_answer() -> None:
    state_store = InMemoryOrchestrationStateStore()
    plan_executor = VerifierFailedExecutor(state_store=state_store)
    orchestrator = SimpleOrchestrator(plan_executor=plan_executor)

    answer = orchestrator.answer(make_request("What was total revenue last month?"))
    state = state_store.get_request_state(answer.trace_id)

    assert answer.confidence == 0.65
    assert answer.warnings[-1].code is ErrorCode.VERIFICATION_FAILED
    assert "table_result" in answer.warnings[-1].message
    assert state is not None
    assert state.stage is RequestStateStage.DEGRADED
    assert state.output_summary is not None
    assert state.output_summary["warning_count"] == 1


def test_orchestrator_runs_final_answer_assembly_verifier_before_saving() -> None:
    orchestrator = SimpleOrchestrator(answer_verifier=MissingSqlAnswerVerifier())

    answer = orchestrator.answer(make_request("What was total revenue last month?"))
    replayed = orchestrator.replay(answer.trace_id)

    assert answer.warnings[-1].code is ErrorCode.VERIFICATION_FAILED
    assert "sql_text is required" in answer.warnings[-1].message
    assert answer.confidence == 0.5
    assert replayed is not None
    assert replayed.answer == answer


def test_orchestrator_blocks_drop_table_before_execution() -> None:
    orchestrator = SimpleOrchestrator()

    answer = orchestrator.answer(make_request("DROP TABLE orders"))

    assert answer.confidence == 0.0
    assert answer.warnings
    assert answer.warnings[0].code is ErrorCode.SQL_DENY_STATEMENT
    assert answer.table_result.rows[0]["status"] == "blocked"


def test_orchestrator_marks_sql_denial_request_state_as_failed() -> None:
    state_store = InMemoryOrchestrationStateStore()
    plan_executor = PlanExecutor(state_store=state_store)
    orchestrator = SimpleOrchestrator(plan_executor=plan_executor)

    answer = orchestrator.answer(make_request("DROP TABLE orders"))
    state = state_store.get_request_state(answer.trace_id)

    assert state is not None
    assert state.stage is RequestStateStage.FAILED
    assert state.error is not None
    assert state.error["code"] == "SQL_DENY_STATEMENT"
    assert state.error["retryable"] is False
    assert state.output_summary is not None
    assert state.output_summary["confidence"] == 0.0


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

    assert terminal_agents == (
        AgentName.SQL,
        AgentName.ANALYTICS,
        AgentName.VERIFIER,
        AgentName.ORCHESTRATOR,
    )
    assert answer.analytics_result is not None
    forecast_result = cast(Mapping[str, Any], answer.analytics_result["forecast_result"])
    assert forecast_result["model_used"] == "moving_average"
    assert len(forecast_result["forecast_series"]) == 3
    assert "v2_result" in answer.analytics_result


def test_orchestrator_persists_v2_analytics_result_by_trace_id() -> None:
    repository = InMemoryAnalyticsRepository()
    orchestrator = SimpleOrchestrator(
        analytics_service=AnalyticsService(repository),
    )

    answer = orchestrator.answer(
        make_request("Predict revenue for next month."),
        trace_id="trc_v2_analytics",
    )

    saved = repository.result_by_trace_id("trc_v2_analytics")
    assert answer.analytics_result is not None
    assert saved is not None
    assert saved.metric_id == "revenue"
    assert saved.result.forecast_points
    assert saved.parameters["grain"] == "month"


def test_sql_only_request_traces_orchestrator_sql_and_verifier_steps() -> None:
    trace_log = InMemoryAgentTraceLog()
    plan_executor = PlanExecutor(tracer=AgentStepTracer(trace_log))
    orchestrator = SimpleOrchestrator(plan_executor=plan_executor)

    answer = orchestrator.answer(make_request("What was total revenue last month?"))
    events = trace_log.list_by_trace_id(answer.trace_id)
    succeeded_agents = tuple(
        event.agent_name
        for event in events
        if event.status is AgentStepStatus.SUCCEEDED
    )

    assert succeeded_agents == (
        AgentName.SQL,
        AgentName.VERIFIER,
        AgentName.ORCHESTRATOR,
    )
    assert events[0].agent_name is AgentName.ORCHESTRATOR
    assert events[0].status is AgentStepStatus.STARTED
    assert events[-1].agent_name is AgentName.ORCHESTRATOR
    assert events[-1].status is AgentStepStatus.SUCCEEDED


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
