"""Execution harness for planned agent steps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from chatbi.core.contracts import (
    AgentName,
    ErrorCode,
    WarningMessage,
)
from chatbi.orchestration.contracts import (
    AgentStepName,
    AgentStepOutput,
    AgentStepOutputStatus,
    timed_out_agent_step_output,
)
from chatbi.orchestration.confidence import ConfidenceAggregator
from chatbi.orchestration.routing import ExecutionPlan, ExecutionStage
from chatbi.orchestration.state import (
    InMemoryOrchestrationStateStore,
    OrchestrationStateStore,
)
from chatbi.orchestration.tracing import AgentStepTracer


class AgentRunner(Protocol):
    def run(self) -> "AgentRunResult":
        """Execute one agent step and return a standard result."""
        ...


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    payload: Mapping[str, object]
    confidence: float


class AgentStepError(Exception):
    """Expected agent-step failure with a structured warning code."""

    def __init__(self, error_code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _empty_step_outputs() -> Mapping[AgentName, AgentStepOutput]:
    return {}


AGENT_STEP_NAMES: dict[AgentName, AgentStepName] = {
    AgentName.ORCHESTRATOR: AgentStepName.ORCHESTRATOR,
    AgentName.SQL: AgentStepName.SQL,
    AgentName.VISUALIZATION: AgentStepName.VISUALIZATION,
    AgentName.ANALYTICS: AgentStepName.ANALYTICS,
    AgentName.RAG: AgentStepName.RAG,
    AgentName.VERIFIER: AgentStepName.VERIFIER,
    AgentName.FILE_DATA: AgentStepName.FILE_DATA,
}


@dataclass(frozen=True, slots=True)
class PlanExecutionResult:
    outputs: Mapping[AgentName, AgentRunResult]
    confidence: float
    warnings: tuple[WarningMessage, ...] = ()
    degraded: bool = False
    skipped_agents: tuple[AgentName, ...] = ()
    step_outputs: Mapping[AgentName, AgentStepOutput] = field(default_factory=_empty_step_outputs)


class PlanExecutor:
    """Run a plan with injected agent runners and trace every step."""

    def __init__(
        self,
        tracer: AgentStepTracer | None = None,
        confidence_aggregator: ConfidenceAggregator | None = None,
        state_store: OrchestrationStateStore | None = None,
        max_attempts: int = 1,
    ) -> None:
        self._tracer = tracer or AgentStepTracer()
        self._confidence_aggregator = confidence_aggregator or ConfidenceAggregator()
        self._state_store = state_store or InMemoryOrchestrationStateStore()
        self._max_attempts = max(1, min(max_attempts, 3))

    @property
    def tracer(self) -> AgentStepTracer:
        return self._tracer

    @property
    def state_store(self) -> OrchestrationStateStore:
        return self._state_store

    def execute(
        self,
        trace_id: str,
        plan: ExecutionPlan,
        runners: Mapping[AgentName, AgentRunner],
    ) -> PlanExecutionResult:
        outputs: dict[AgentName, AgentRunResult] = {}
        completed_agents: set[AgentName] = set()
        step_outputs: dict[AgentName, AgentStepOutput] = {}
        warnings: list[WarningMessage] = []
        skipped_agents: list[AgentName] = []

        for step in plan.steps:
            if any(dependency not in completed_agents for dependency in step.depends_on):
                self._tracer.record_skipped(
                    trace_id=trace_id,
                    agent_name=step.agent_name,
                    summary="Dependency did not complete.",
                )
                skipped_agents.append(step.agent_name)
                skipped_output = AgentStepOutput(
                    status=AgentStepOutputStatus.SKIPPED,
                    result=None,
                    confidence=0.0,
                    warnings=[],
                    metrics={},
                    error=None,
                )
                step_outputs[step.agent_name] = skipped_output
                self._record_step_output(trace_id, step.agent_name, skipped_output)
                continue

            runner = runners.get(step.agent_name)
            if runner is None:
                self._tracer.record_skipped(
                    trace_id=trace_id,
                    agent_name=step.agent_name,
                    summary="Agent runner is not configured.",
                )
                skipped_agents.append(step.agent_name)
                skipped_output = AgentStepOutput(
                    status=AgentStepOutputStatus.SKIPPED,
                    result=None,
                    confidence=0.0,
                    warnings=[],
                    metrics={},
                    error=None,
                )
                step_outputs[step.agent_name] = skipped_output
                self._record_step_output(trace_id, step.agent_name, skipped_output)
                continue

            try:
                run_result = self._run_step_with_idempotency(
                    trace_id=trace_id,
                    agent_name=step.agent_name,
                    runner=runner,
                )
                outputs[step.agent_name] = run_result
                completed_agents.add(step.agent_name)
                step_outputs[step.agent_name] = self._succeeded_step_output(run_result)
            except AgentStepError as exc:
                warnings.append(
                    self._agent_warning(step.agent_name, exc.message, exc.error_code)
                )
                failed_output = self._failed_step_output(exc.message, exc.error_code)
                step_outputs[step.agent_name] = failed_output
                self._record_step_output(trace_id, step.agent_name, failed_output)
                if step.stage is ExecutionStage.SQL:
                    skipped_agents.extend(
                        self._skip_remaining_after_failure(trace_id, plan, step.agent_name)
                    )
                    break
                completed_agents.add(step.agent_name)
            except TimeoutError:
                warnings.append(
                    self._agent_warning(
                        step.agent_name,
                        "Agent timed out before completing.",
                        ErrorCode.AGENT_TIMEOUT,
                    )
                )
                timeout_output = timed_out_agent_step_output()
                step_outputs[step.agent_name] = timeout_output
                self._record_step_output(trace_id, step.agent_name, timeout_output)
                if step.stage is ExecutionStage.SQL:
                    skipped_agents.extend(
                        self._skip_remaining_after_failure(trace_id, plan, step.agent_name)
                    )
                    break
                completed_agents.add(step.agent_name)
            except Exception:
                error_code = self._non_critical_error_code(step.agent_name)
                warnings.append(
                    self._agent_warning(
                        step.agent_name,
                        "Agent failed before completing.",
                        error_code,
                    )
                )
                degraded_output = self._degraded_step_output(
                    message="Agent failed before completing.",
                    error_code=error_code,
                )
                step_outputs[step.agent_name] = degraded_output
                self._record_step_output(trace_id, step.agent_name, degraded_output)
                if step.stage is ExecutionStage.SQL:
                    skipped_agents.extend(
                        self._skip_remaining_after_failure(trace_id, plan, step.agent_name)
                    )
                    break
                completed_agents.add(step.agent_name)

        confidence_result = self._confidence_aggregator.aggregate(
            {
                agent_name: output.confidence
                for agent_name, output in outputs.items()
                if agent_name in {AgentName.SQL, AgentName.VERIFIER, AgentName.RAG, AgentName.ANALYTICS}
            }
        )
        warnings.extend(confidence_result.warnings)

        return PlanExecutionResult(
            outputs=outputs,
            confidence=confidence_result.confidence,
            warnings=tuple(warnings),
            degraded=bool(warnings or skipped_agents),
            skipped_agents=tuple(skipped_agents),
            step_outputs=step_outputs,
        )

    def _record_step_output(
        self,
        trace_id: str,
        agent_name: AgentName,
        step_output: AgentStepOutput,
    ) -> None:
        self._state_store.save_step(
            idempotency_key=self._idempotency_key(trace_id, agent_name, 1),
            step_output=step_output,
        )

    def _run_step_with_idempotency(
        self,
        trace_id: str,
        agent_name: AgentName,
        runner: AgentRunner,
    ) -> AgentRunResult:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            idempotency_key = self._idempotency_key(trace_id, agent_name, attempt)
            cached = self._state_store.get_successful_step(idempotency_key)
            if cached is not None:
                if cached.run_result is None:
                    raise RuntimeError("successful step cache is missing run_result")
                return cached.run_result

            try:
                result = self._tracer.run_step(
                    trace_id=trace_id,
                    agent_name=agent_name,
                    action=runner.run,
                )
            except TimeoutError as exc:
                last_error = exc
                self._state_store.save_step(
                    idempotency_key=idempotency_key,
                    step_output=timed_out_agent_step_output(),
                )
                continue
            except AgentStepError as exc:
                last_error = exc
                self._state_store.save_step(
                    idempotency_key=idempotency_key,
                    step_output=self._failed_step_output(exc.message, exc.error_code),
                )
                continue
            except Exception as exc:
                last_error = exc
                self._state_store.save_step(
                    idempotency_key=idempotency_key,
                    step_output=self._failed_step_output(
                        message="Agent failed before completing.",
                        error_code=ErrorCode.AGENT_PARTIAL_FAILURE,
                    ),
                )
                continue

            self._state_store.save_successful_step(
                idempotency_key=idempotency_key,
                run_result=result,
                step_output=self._succeeded_step_output(result),
            )
            return result

        if last_error is None:
            raise RuntimeError("agent step did not execute")
        raise last_error

    def _idempotency_key(self, trace_id: str, agent_name: AgentName, attempt: int) -> str:
        return f"{trace_id}:{AGENT_STEP_NAMES[agent_name].value}:{attempt}"

    def _succeeded_step_output(self, run_result: AgentRunResult) -> AgentStepOutput:
        return AgentStepOutput(
            status=AgentStepOutputStatus.SUCCEEDED,
            result=run_result.payload,
            confidence=run_result.confidence,
            warnings=[],
            metrics={},
            error=None,
        )

    def _failed_step_output(
        self,
        message: str,
        error_code: ErrorCode,
    ) -> AgentStepOutput:
        return AgentStepOutput(
            status=AgentStepOutputStatus.FAILED,
            result=None,
            confidence=0.0,
            warnings=[],
            metrics={},
            error={
                "code": error_code.value,
                "message": message,
                "retryable": error_code is ErrorCode.AGENT_PARTIAL_FAILURE,
            },
        )

    def _degraded_step_output(
        self,
        message: str,
        error_code: ErrorCode,
    ) -> AgentStepOutput:
        return AgentStepOutput(
            status=AgentStepOutputStatus.DEGRADED,
            result=None,
            confidence=0.0,
            warnings=[],
            metrics={},
            error={
                "code": error_code.value,
                "message": message,
                "retryable": True,
            },
        )

    def _non_critical_error_code(self, agent_name: AgentName) -> ErrorCode:
        if agent_name is AgentName.RAG:
            return ErrorCode.RAG_UNAVAILABLE
        return ErrorCode.AGENT_PARTIAL_FAILURE

    def _skip_remaining_after_failure(
        self,
        trace_id: str,
        plan: ExecutionPlan,
        failed_agent: AgentName,
    ) -> list[AgentName]:
        skipped_agents: list[AgentName] = []
        seen_failed_agent = False
        for step in plan.steps:
            if step.agent_name is failed_agent:
                seen_failed_agent = True
                continue
            if not seen_failed_agent:
                continue
            self._tracer.record_skipped(
                trace_id=trace_id,
                agent_name=step.agent_name,
                summary=f"Skipped because {failed_agent.value} did not complete.",
            )
            self._record_step_output(
                trace_id=trace_id,
                agent_name=step.agent_name,
                step_output=AgentStepOutput(
                    status=AgentStepOutputStatus.SKIPPED,
                    result=None,
                    confidence=0.0,
                    warnings=[],
                    metrics={},
                    error=None,
                ),
            )
            skipped_agents.append(step.agent_name)
        return skipped_agents

    def _agent_warning(
        self,
        agent_name: AgentName,
        message: str,
        error_code: ErrorCode,
    ) -> WarningMessage:
        return WarningMessage(
            code=error_code,
            message=f"{agent_name.value}: {message}",
        )
