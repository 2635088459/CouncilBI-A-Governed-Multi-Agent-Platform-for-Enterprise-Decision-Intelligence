"""Typed contracts for the v2 agent orchestration layer.

These models follow ``spec/version2/02-agent-orchestration.spec.md``. They are
small on purpose: the orchestrator, agents, retry logic, and recovery logic all
share these shapes before any Redis, PostgreSQL, or worker implementation is
introduced.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from chatbi.core.architecture_contracts import ErrorPayloadV2, LocaleV2, UserRoleV2, WarningPayloadV2


MIN_DEADLINE_MS = 100
MAX_DEADLINE_MS = 60_000
MAX_QUESTION_LENGTH = 2_000
MAX_AGENT_ATTEMPT = 3


class AgentStepName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    SQL = "sql"
    VISUALIZATION = "visualization"
    ANALYTICS = "analytics"
    RAG = "rag"
    VERIFIER = "verifier"
    FILE_DATA = "file_data"


class AgentStepOutputStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


def _empty_warnings() -> list[WarningPayloadV2]:
    return []


def _empty_metrics() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    role: UserRoleV2
    locale: LocaleV2

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if self.role not in ("business_user", "analyst", "admin"):
            raise ValueError("role must be business_user, analyst, or admin")
        if self.locale not in ("en", "zh-CN"):
            raise ValueError("locale must be en or zh-CN")


@dataclass(frozen=True, slots=True)
class OrchestrationRequest:
    trace_id: str
    session_id: str
    user_context: UserContext
    question: str
    semantic_context: Mapping[str, Any]
    deadline_ms: int

    def __post_init__(self) -> None:
        _require_non_empty("trace_id", self.trace_id)
        _require_non_empty("session_id", self.session_id)
        question_length = len(self.question.strip())
        if question_length < 1 or question_length > MAX_QUESTION_LENGTH:
            raise ValueError("question length must be between 1 and 2000 characters")
        _require_deadline_ms(self.deadline_ms)


@dataclass(frozen=True, slots=True)
class AgentStepInput:
    trace_id: str
    step_name: AgentStepName
    attempt: int
    task_payload: Mapping[str, Any]
    deadline_ms: int

    def __post_init__(self) -> None:
        _require_non_empty("trace_id", self.trace_id)
        if not 1 <= self.attempt <= MAX_AGENT_ATTEMPT:
            raise ValueError("attempt must be between 1 and 3")
        _require_deadline_ms(self.deadline_ms)

    @property
    def idempotency_key(self) -> str:
        return f"{self.trace_id}:{self.step_name.value}:{self.attempt}"


@dataclass(frozen=True, slots=True)
class AgentStepOutput:
    status: AgentStepOutputStatus
    result: Mapping[str, Any] | None
    confidence: float
    warnings: list[WarningPayloadV2] = field(default_factory=_empty_warnings)
    metrics: Mapping[str, Any] = field(default_factory=_empty_metrics)
    error: ErrorPayloadV2 | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.status is AgentStepOutputStatus.TIMED_OUT:
            if self.error is None or self.error.get("code") != "AGENT_TIMEOUT":
                raise ValueError("timed_out output must include error.code == AGENT_TIMEOUT")


def timed_out_agent_step_output(message: str = "Agent exceeded its deadline.") -> AgentStepOutput:
    return AgentStepOutput(
        status=AgentStepOutputStatus.TIMED_OUT,
        result=None,
        confidence=0.0,
        warnings=[],
        metrics={},
        error={
            "code": "AGENT_TIMEOUT",
            "message": message,
            "retryable": True,
        },
    )


def _require_non_empty(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_deadline_ms(deadline_ms: int) -> None:
    if not MIN_DEADLINE_MS <= deadline_ms <= MAX_DEADLINE_MS:
        raise ValueError("deadline_ms must be between 100 and 60000")
