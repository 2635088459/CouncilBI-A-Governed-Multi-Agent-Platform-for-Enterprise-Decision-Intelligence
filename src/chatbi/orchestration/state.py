"""Short-lived orchestration state storage.

The v2 spec calls for Redis-backed in-flight state keyed by ``trace_id``. This
module starts with a tiny in-memory implementation that has the same shape, so
the executor can depend on a storage contract instead of keeping private state
inside itself.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from chatbi.core.architecture_contracts import ErrorPayloadV2
from chatbi.orchestration.contracts import AgentStepOutput, AgentStepOutputStatus

if TYPE_CHECKING:
    from chatbi.orchestration.executor import AgentRunResult


class OrchestrationStateStore(Protocol):
    def get_request_state(self, trace_id: str) -> "OrchestrationRequestState | None":
        """Return request-level in-flight state keyed by trace id."""
        ...

    def save_request_state(self, state: "OrchestrationRequestState") -> None:
        """Persist request-level in-flight state keyed by trace id."""
        ...

    def get_step(self, idempotency_key: str) -> "StoredAgentStep | None":
        """Return the latest stored state for one idempotency key."""
        ...

    def get_successful_step(self, idempotency_key: str) -> "StoredAgentStep | None":
        """Return a previously succeeded step for the exact idempotency key."""
        ...

    def save_step(
        self,
        idempotency_key: str,
        step_output: AgentStepOutput,
        run_result: "AgentRunResult | None" = None,
    ) -> None:
        """Persist the latest state for one step, successful or not."""
        ...

    def save_successful_step(
        self,
        idempotency_key: str,
        run_result: AgentRunResult,
        step_output: AgentStepOutput,
    ) -> None:
        """Persist one successful step result for replay and recovery."""
        ...

    def list_successful_steps(self, trace_id: str) -> tuple["StoredAgentStep", ...]:
        """Return successful steps belonging to one trace id."""
        ...


class RequestStateStage(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"


def _empty_summary() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class OrchestrationRequestState:
    trace_id: str
    stage: RequestStateStage
    input_summary: Mapping[str, object] = field(default_factory=_empty_summary)
    output_summary: Mapping[str, object] | None = None
    error: ErrorPayloadV2 | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.trace_id.strip():
            raise ValueError("trace_id is required")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must be greater than or equal to 0")
        if self.stage is RequestStateStage.FAILED and self.error is None:
            raise ValueError("failed request state must include error")


@dataclass(frozen=True, slots=True)
class StoredAgentStep:
    idempotency_key: str
    trace_id: str
    run_result: AgentRunResult | None
    step_output: AgentStepOutput


def _empty_steps() -> Mapping[str, StoredAgentStep]:
    return {}


def _empty_request_states() -> Mapping[str, OrchestrationRequestState]:
    return {}


@dataclass(slots=True)
class InMemoryOrchestrationStateStore:
    """Redis-shaped state store for tests and local development."""

    _request_states: Mapping[str, OrchestrationRequestState] = field(default_factory=_empty_request_states)
    _steps: Mapping[str, StoredAgentStep] = field(default_factory=_empty_steps)
    _mutable_request_states: MutableMapping[str, OrchestrationRequestState] = field(init=False)
    _mutable_steps: MutableMapping[str, StoredAgentStep] = field(init=False)

    def __post_init__(self) -> None:
        self._mutable_request_states = dict(self._request_states)
        self._mutable_steps = dict(self._steps)

    def get_request_state(self, trace_id: str) -> OrchestrationRequestState | None:
        return self._mutable_request_states.get(trace_id)

    def save_request_state(self, state: OrchestrationRequestState) -> None:
        self._mutable_request_states[state.trace_id] = state

    def get_step(self, idempotency_key: str) -> StoredAgentStep | None:
        return self._mutable_steps.get(idempotency_key)

    def get_successful_step(self, idempotency_key: str) -> StoredAgentStep | None:
        stored = self._mutable_steps.get(idempotency_key)
        if stored is None or stored.run_result is None:
            return None
        if stored.step_output.status is not AgentStepOutputStatus.SUCCEEDED:
            return None
        return stored

    def save_step(
        self,
        idempotency_key: str,
        step_output: AgentStepOutput,
        run_result: AgentRunResult | None = None,
    ) -> None:
        trace_id = idempotency_key.split(":", 1)[0]
        self._mutable_steps[idempotency_key] = StoredAgentStep(
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            run_result=run_result,
            step_output=step_output,
        )

    def save_successful_step(
        self,
        idempotency_key: str,
        run_result: AgentRunResult,
        step_output: AgentStepOutput,
    ) -> None:
        self.save_step(idempotency_key, step_output, run_result)

    def list_successful_steps(self, trace_id: str) -> tuple[StoredAgentStep, ...]:
        return tuple(
            step
            for step in self._mutable_steps.values()
            if step.trace_id == trace_id
            and step.run_result is not None
            and step.step_output.status is AgentStepOutputStatus.SUCCEEDED
        )
