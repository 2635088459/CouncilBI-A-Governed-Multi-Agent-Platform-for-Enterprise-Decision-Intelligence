from dataclasses import dataclass

from chatbi.core.contracts import AgentName, AgentStepStatus, ErrorCode, new_trace_id
from chatbi.orchestration.contracts import AgentStepOutputStatus
from chatbi.orchestration.executor import AgentRunResult, AgentStepError, PlanExecutor
from chatbi.orchestration.routing import ExecutionPlanBuilder, TaskType
from chatbi.orchestration.state import InMemoryOrchestrationStateStore
from chatbi.orchestration.tracing import AgentStepTracer, InMemoryAgentTraceLog


@dataclass(frozen=True, slots=True)
class FakeRunner:
    result: AgentRunResult

    def run(self) -> AgentRunResult:
        return self.result


class TimeoutRunner:
    def run(self) -> AgentRunResult:
        raise TimeoutError("agent timed out")


class FailingRunner:
    def run(self) -> AgentRunResult:
        raise RuntimeError("agent failed")


class DeniedSqlRunner:
    def run(self) -> AgentRunResult:
        raise AgentStepError(
            error_code=ErrorCode.SQL_DENY_STATEMENT,
            message="Only SELECT statements are allowed.",
        )


class CountingRunner:
    def __init__(self, result: AgentRunResult) -> None:
        self.result = result
        self.run_count = 0

    def run(self) -> AgentRunResult:
        self.run_count += 1
        return self.result


class FlakyRunner:
    def __init__(self, result: AgentRunResult) -> None:
        self.result = result
        self.run_count = 0

    def run(self) -> AgentRunResult:
        self.run_count += 1
        if self.run_count == 1:
            raise RuntimeError("temporary failure")
        return self.result


def test_plan_executor_aggregates_successful_agent_outputs() -> None:
    trace_id = new_trace_id()
    plan = ExecutionPlanBuilder().build(TaskType.CHART)
    executor = PlanExecutor()

    result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: FakeRunner(AgentRunResult(payload={"sql": "SELECT 1"}, confidence=0.8)),
            AgentName.VISUALIZATION: FakeRunner(AgentRunResult(payload={"chart": "line"}, confidence=0.9)),
            AgentName.VERIFIER: FakeRunner(AgentRunResult(payload={"verified": True}, confidence=0.95)),
        },
    )

    assert result.outputs[AgentName.SQL].payload == {"sql": "SELECT 1"}
    assert result.outputs[AgentName.VISUALIZATION].payload == {"chart": "line"}
    assert result.outputs[AgentName.VERIFIER].payload == {"verified": True}
    assert result.step_outputs[AgentName.SQL].status is AgentStepOutputStatus.SUCCEEDED
    assert result.step_outputs[AgentName.VERIFIER].status is AgentStepOutputStatus.SUCCEEDED
    assert result.confidence == 0.875
    assert result.degraded is False
    assert result.warnings == ()


def test_plan_executor_skips_fanout_when_sql_times_out() -> None:
    trace_id = new_trace_id()
    trace_log = InMemoryAgentTraceLog()
    state_store = InMemoryOrchestrationStateStore()
    plan = ExecutionPlanBuilder().build(TaskType.CHART)
    executor = PlanExecutor(
        tracer=AgentStepTracer(trace_log),
        state_store=state_store,
    )

    result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: TimeoutRunner(),
            AgentName.VISUALIZATION: FakeRunner(AgentRunResult(payload={"chart": "line"}, confidence=0.9)),
        },
    )
    events = trace_log.list_by_trace_id(trace_id)

    assert result.degraded is True
    assert result.outputs == {}
    assert result.skipped_agents == (AgentName.VISUALIZATION, AgentName.VERIFIER)
    assert result.warnings[0].code is ErrorCode.AGENT_TIMEOUT
    assert events[0].status is AgentStepStatus.STARTED
    assert events[1].status is AgentStepStatus.TIMED_OUT
    assert events[1].summary == "AGENT_TIMEOUT"
    assert result.step_outputs[AgentName.SQL].status is AgentStepOutputStatus.TIMED_OUT
    timeout_error = result.step_outputs[AgentName.SQL].error
    assert timeout_error is not None
    assert timeout_error["code"] == "AGENT_TIMEOUT"
    stored_timeout = state_store.get_step(f"{trace_id}:sql:1")
    assert stored_timeout is not None
    assert stored_timeout.step_output.status is AgentStepOutputStatus.TIMED_OUT
    stored_timeout_error = stored_timeout.step_output.error
    assert stored_timeout_error is not None
    assert stored_timeout_error["code"] == "AGENT_TIMEOUT"
    assert tuple(event.agent_name for event in events[2:]) == (
        AgentName.VISUALIZATION,
        AgentName.VERIFIER,
    )
    assert all(event.status is AgentStepStatus.SKIPPED for event in events[2:])


def test_plan_executor_does_not_start_visualization_when_sql_guardrail_denies() -> None:
    trace_id = new_trace_id()
    trace_log = InMemoryAgentTraceLog()
    plan = ExecutionPlanBuilder().build(TaskType.CHART)
    visualization_runner = CountingRunner(
        AgentRunResult(payload={"chart": "line"}, confidence=0.9)
    )
    executor = PlanExecutor(tracer=AgentStepTracer(trace_log))

    result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: DeniedSqlRunner(),
            AgentName.VISUALIZATION: visualization_runner,
            AgentName.VERIFIER: FakeRunner(AgentRunResult(payload={"verified": True}, confidence=0.9)),
        },
    )
    events = trace_log.list_by_trace_id(trace_id)

    assert visualization_runner.run_count == 0
    assert AgentName.VISUALIZATION not in result.outputs
    assert result.skipped_agents == (AgentName.VISUALIZATION, AgentName.VERIFIER)
    assert result.warnings[0].code is ErrorCode.SQL_DENY_STATEMENT
    assert result.step_outputs[AgentName.SQL].status is AgentStepOutputStatus.FAILED
    assert tuple(event.agent_name for event in events) == (
        AgentName.SQL,
        AgentName.SQL,
        AgentName.VISUALIZATION,
        AgentName.VERIFIER,
    )
    assert tuple(event.status for event in events) == (
        AgentStepStatus.STARTED,
        AgentStepStatus.FAILED,
        AgentStepStatus.SKIPPED,
        AgentStepStatus.SKIPPED,
    )


def test_plan_executor_returns_degraded_result_when_fanout_fails() -> None:
    trace_id = new_trace_id()
    plan = ExecutionPlanBuilder().build(TaskType.ANALYTICS)
    executor = PlanExecutor()

    result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: FakeRunner(AgentRunResult(payload={"sql": "SELECT 1"}, confidence=0.8)),
            AgentName.ANALYTICS: FailingRunner(),
        },
    )

    assert result.outputs[AgentName.SQL].payload == {"sql": "SELECT 1"}
    assert AgentName.ANALYTICS not in result.outputs
    assert AgentName.VERIFIER not in result.outputs
    assert result.degraded is True
    assert result.warnings[0].code is ErrorCode.AGENT_PARTIAL_FAILURE


def test_plan_executor_degrades_rag_failure_and_still_runs_verifier() -> None:
    trace_id = new_trace_id()
    plan = ExecutionPlanBuilder().build(TaskType.RAG_EXPLANATION)
    executor = PlanExecutor()

    result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: FakeRunner(AgentRunResult(payload={"sql": "SELECT 1"}, confidence=0.8)),
            AgentName.RAG: FailingRunner(),
            AgentName.VERIFIER: FakeRunner(AgentRunResult(payload={"verified": True}, confidence=0.9)),
        },
    )

    assert result.outputs[AgentName.SQL].payload == {"sql": "SELECT 1"}
    assert AgentName.RAG not in result.outputs
    assert result.outputs[AgentName.VERIFIER].payload == {"verified": True}
    assert result.degraded is True
    assert result.warnings[0].code is ErrorCode.RAG_UNAVAILABLE
    assert result.step_outputs[AgentName.RAG].status is AgentStepOutputStatus.DEGRADED
    rag_error = result.step_outputs[AgentName.RAG].error
    assert rag_error is not None
    assert rag_error["code"] == "RAG_UNAVAILABLE"


def test_plan_executor_reuses_successful_step_for_same_idempotency_key() -> None:
    trace_id = new_trace_id()
    plan = ExecutionPlanBuilder().build(TaskType.SQL_QUERY)
    sql_runner = CountingRunner(AgentRunResult(payload={"sql": "SELECT 1"}, confidence=0.8))
    verifier_runner = CountingRunner(AgentRunResult(payload={"verified": True}, confidence=0.9))
    executor = PlanExecutor()

    first_result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: sql_runner,
            AgentName.VERIFIER: verifier_runner,
        },
    )
    replayed_result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: sql_runner,
            AgentName.VERIFIER: verifier_runner,
        },
    )

    assert sql_runner.run_count == 1
    assert verifier_runner.run_count == 1
    assert replayed_result.outputs[AgentName.SQL] == first_result.outputs[AgentName.SQL]
    assert replayed_result.outputs[AgentName.VERIFIER] == first_result.outputs[AgentName.VERIFIER]


def test_plan_executor_reuses_successful_step_after_orchestrator_restart() -> None:
    trace_id = new_trace_id()
    state_store = InMemoryOrchestrationStateStore()
    plan = ExecutionPlanBuilder().build(TaskType.SQL_QUERY)
    first_sql_runner = CountingRunner(
        AgentRunResult(payload={"sql": "SELECT 1"}, confidence=0.8)
    )
    first_verifier_runner = CountingRunner(
        AgentRunResult(payload={"verified": True}, confidence=0.9)
    )
    first_executor = PlanExecutor(state_store=state_store)

    first_result = first_executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: first_sql_runner,
            AgentName.VERIFIER: first_verifier_runner,
        },
    )

    replay_sql_runner = CountingRunner(
        AgentRunResult(payload={"sql": "SHOULD NOT RUN"}, confidence=0.1)
    )
    replay_verifier_runner = CountingRunner(
        AgentRunResult(payload={"verified": False}, confidence=0.1)
    )
    restarted_executor = PlanExecutor(state_store=state_store)
    replayed_result = restarted_executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: replay_sql_runner,
            AgentName.VERIFIER: replay_verifier_runner,
        },
    )

    assert first_sql_runner.run_count == 1
    assert first_verifier_runner.run_count == 1
    assert replay_sql_runner.run_count == 0
    assert replay_verifier_runner.run_count == 0
    assert replayed_result.outputs[AgentName.SQL] == first_result.outputs[AgentName.SQL]
    assert replayed_result.outputs[AgentName.VERIFIER] == first_result.outputs[AgentName.VERIFIER]


def test_plan_executor_retries_failed_attempt_and_records_attempt_state() -> None:
    trace_id = new_trace_id()
    trace_log = InMemoryAgentTraceLog()
    state_store = InMemoryOrchestrationStateStore()
    plan = ExecutionPlanBuilder().build(TaskType.SQL_QUERY)
    sql_runner = FlakyRunner(AgentRunResult(payload={"sql": "SELECT 1"}, confidence=0.8))
    verifier_runner = FakeRunner(AgentRunResult(payload={"verified": True}, confidence=0.9))
    executor = PlanExecutor(
        tracer=AgentStepTracer(trace_log),
        state_store=state_store,
        max_attempts=2,
    )

    result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: sql_runner,
            AgentName.VERIFIER: verifier_runner,
        },
    )
    sql_events = tuple(
        event
        for event in trace_log.list_by_trace_id(trace_id)
        if event.agent_name is AgentName.SQL
    )
    failed_attempt = state_store.get_step(f"{trace_id}:sql:1")
    successful_attempt = state_store.get_successful_step(f"{trace_id}:sql:2")

    assert sql_runner.run_count == 2
    assert result.outputs[AgentName.SQL].payload == {"sql": "SELECT 1"}
    assert tuple(event.status for event in sql_events) == (
        AgentStepStatus.STARTED,
        AgentStepStatus.FAILED,
        AgentStepStatus.STARTED,
        AgentStepStatus.SUCCEEDED,
    )
    assert failed_attempt is not None
    assert failed_attempt.step_output.status is AgentStepOutputStatus.FAILED
    assert successful_attempt is not None
    assert successful_attempt.step_output.status is AgentStepOutputStatus.SUCCEEDED
