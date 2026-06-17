"""Execution harness for planned agent steps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from chatbi.core.contracts import (
    AgentName,
    ErrorCode,
    WarningMessage,
)
from chatbi.orchestration.confidence import ConfidenceAggregator
from chatbi.orchestration.routing import ExecutionPlan, ExecutionStage
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


@dataclass(frozen=True, slots=True)
class PlanExecutionResult:
    outputs: Mapping[AgentName, AgentRunResult]
    confidence: float
    warnings: tuple[WarningMessage, ...] = ()
    degraded: bool = False
    skipped_agents: tuple[AgentName, ...] = ()


class PlanExecutor:
    """Run a plan with injected agent runners and trace every step."""

    def __init__(
        self,
        tracer: AgentStepTracer | None = None,
        confidence_aggregator: ConfidenceAggregator | None = None,
    ) -> None:
        self._tracer = tracer or AgentStepTracer()
        self._confidence_aggregator = confidence_aggregator or ConfidenceAggregator()

    @property
    def tracer(self) -> AgentStepTracer:
        return self._tracer

    def execute(
        self,
        trace_id: str,
        plan: ExecutionPlan,
        runners: Mapping[AgentName, AgentRunner],
    ) -> PlanExecutionResult:
        outputs: dict[AgentName, AgentRunResult] = {}
        warnings: list[WarningMessage] = []
        skipped_agents: list[AgentName] = []

        for step in plan.steps:
            if any(dependency not in outputs for dependency in step.depends_on):
                self._tracer.record_skipped(
                    trace_id=trace_id,
                    agent_name=step.agent_name,
                    summary="Dependency did not complete.",
                )
                skipped_agents.append(step.agent_name)
                continue

            runner = runners.get(step.agent_name)
            if runner is None:
                self._tracer.record_skipped(
                    trace_id=trace_id,
                    agent_name=step.agent_name,
                    summary="Agent runner is not configured.",
                )
                skipped_agents.append(step.agent_name)
                continue

            try:
                outputs[step.agent_name] = self._tracer.run_step(
                    trace_id=trace_id,
                    agent_name=step.agent_name,
                    action=runner.run,
                )
            except AgentStepError as exc:
                warnings.append(
                    self._agent_warning(step.agent_name, exc.message, exc.error_code)
                )
                skipped_agents.extend(
                    self._skip_remaining_after_failure(trace_id, plan, step.agent_name)
                )
                break
            except TimeoutError:
                warnings.append(
                    self._agent_warning(
                        step.agent_name,
                        "Agent timed out before completing.",
                        ErrorCode.AGENT_PARTIAL_FAILURE,
                    )
                )
                skipped_agents.extend(
                    self._skip_remaining_after_failure(trace_id, plan, step.agent_name)
                )
                break
            except Exception:
                warnings.append(
                    self._agent_warning(
                        step.agent_name,
                        "Agent failed before completing.",
                        ErrorCode.AGENT_PARTIAL_FAILURE,
                    )
                )
                if step.stage is ExecutionStage.SQL:
                    skipped_agents.extend(
                        self._skip_remaining_after_failure(trace_id, plan, step.agent_name)
                    )
                    break

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
        )

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
