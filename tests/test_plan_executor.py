from dataclasses import dataclass

from chatbi.core.contracts import AgentName, AgentStepStatus, ErrorCode, new_trace_id
from chatbi.orchestration.executor import AgentRunResult, PlanExecutor
from chatbi.orchestration.routing import ExecutionPlanBuilder, TaskType
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


def test_plan_executor_aggregates_successful_agent_outputs() -> None:
    trace_id = new_trace_id()
    plan = ExecutionPlanBuilder().build(TaskType.KPI_QUERY)
    executor = PlanExecutor()

    result = executor.execute(
        trace_id=trace_id,
        plan=plan,
        runners={
            AgentName.SQL: FakeRunner(AgentRunResult(payload={"sql": "SELECT 1"}, confidence=0.8)),
            AgentName.VISUALIZATION: FakeRunner(AgentRunResult(payload={"chart": "line"}, confidence=0.9)),
        },
    )

    assert result.outputs[AgentName.SQL].payload == {"sql": "SELECT 1"}
    assert result.outputs[AgentName.VISUALIZATION].payload == {"chart": "line"}
    assert result.confidence == 0.8
    assert result.degraded is False
    assert result.warnings == ()


def test_plan_executor_skips_fanout_when_sql_times_out() -> None:
    trace_id = new_trace_id()
    trace_log = InMemoryAgentTraceLog()
    plan = ExecutionPlanBuilder().build(TaskType.KPI_QUERY)
    executor = PlanExecutor(tracer=AgentStepTracer(trace_log))

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
    assert result.skipped_agents == (AgentName.VISUALIZATION,)
    assert result.warnings[0].code is ErrorCode.AGENT_PARTIAL_FAILURE
    assert events[0].status is AgentStepStatus.STARTED
    assert events[1].status is AgentStepStatus.FAILED
    assert events[2].agent_name is AgentName.VISUALIZATION
    assert events[2].status is AgentStepStatus.SKIPPED


def test_plan_executor_returns_degraded_result_when_fanout_fails() -> None:
    trace_id = new_trace_id()
    plan = ExecutionPlanBuilder().build(TaskType.FORECAST)
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
    assert result.degraded is True
    assert result.warnings[0].code is ErrorCode.AGENT_PARTIAL_FAILURE
