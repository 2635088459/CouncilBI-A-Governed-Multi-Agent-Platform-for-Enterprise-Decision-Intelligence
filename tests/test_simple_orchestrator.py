from chatbi.core.contracts import (
    AgentName,
    AgentStepStatus,
    ErrorCode,
    Locale,
    QueryRequest,
    UserRole,
)
from chatbi.orchestration.executor import PlanExecutor
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator
from chatbi.orchestration.tracing import AgentStepTracer, InMemoryAgentTraceLog


def make_request(question: str = "Show revenue trend.") -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question=question,
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
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
