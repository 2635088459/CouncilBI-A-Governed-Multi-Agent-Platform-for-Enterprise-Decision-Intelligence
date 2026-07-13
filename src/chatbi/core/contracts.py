"""Core contracts for the Overall Architecture spec.

This module is intentionally small: it turns spec/01-overall-architecture
into typed Python objects before any endpoint, agent, database, or LLM code is
implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Protocol
from uuid import uuid4


class Locale(StrEnum):
    EN = "en"
    ZH_CN = "zh-CN"


class UserRole(StrEnum):
    BUSINESS_USER = "business_user"
    ANALYST = "analyst"
    ADMIN = "admin"


class AgentName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    SQL = "sql_agent"
    VISUALIZATION = "visualization_agent"
    ANALYTICS = "analytics_agent"
    RAG = "rag_agent"
    VERIFIER = "verifier_agent"
    FILE_DATA = "file_data_agent"


class AgentStepStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


class QueryHistoryStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TraceLinkedRecordType(StrEnum):
    MESSAGE = "message"
    QUERY_RESULT = "query_result"
    AGENT_TRACE = "agent_trace"
    AUDIT_EVENT = "audit_event"
    EVAL_SCORE = "eval_score"


class ErrorCode(StrEnum):
    SQL_DENY_STATEMENT = "SQL_DENY_STATEMENT"
    # 10-followups/13: distinct from SQL_DENY_STATEMENT — the model's output
    # contained no dangerous DML/DDL keyword; it just wasn't a recognizable
    # read-only query. Kept separate so the API layer and frontend can stop
    # describing this as a data-modification attempt.
    SQL_DENY_UNRECOGNIZED_OUTPUT = "SQL_DENY_UNRECOGNIZED_OUTPUT"
    SQL_DENY_OBJECT = "SQL_DENY_OBJECT"
    SQL_DENY_FUNCTION = "SQL_DENY_FUNCTION"
    SQL_DENY_TIMEOUT = "SQL_DENY_TIMEOUT"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_PARTIAL_FAILURE = "AGENT_PARTIAL_FAILURE"
    RAG_UNAVAILABLE = "RAG_UNAVAILABLE"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNSUPPORTED_QUESTION = "UNSUPPORTED_QUESTION"
    LLM_PROVIDER_FAILURE = "LLM_PROVIDER_FAILURE"
    LLM_PROVIDER_TIMEOUT = "LLM_PROVIDER_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ChartType(StrEnum):
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    STACKED_BAR = "stacked_bar"
    FORECAST = "forecast"


class GuardrailDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


def new_trace_id() -> str:
    """Create the trace id required by every architecture-level response."""

    return f"trc_{uuid4().hex}"


def new_agent_trace_id() -> str:
    return f"agt_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class QueryRequest:
    user_id: str
    session_id: str
    question: str
    locale: Locale
    role: UserRole


@dataclass(frozen=True, slots=True)
class TableResult:
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ChartSpec:
    chart_type: ChartType
    x_field: str
    y_fields: tuple[str, ...]
    title: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    source_id: str
    title: str
    citation_anchor: str
    snippet: str
    publish_time: datetime | None = None
    relevance_score: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError("relevance_score must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class RetrievalStats:
    candidate_count: int
    filtered_count: int
    reranked_count: int
    selected_count: int
    latency_ms: float

    def __post_init__(self) -> None:
        counts = (
            self.candidate_count,
            self.filtered_count,
            self.reranked_count,
            self.selected_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("retrieval counts must be greater than or equal to 0")
        if self.latency_ms < 0:
            raise ValueError("retrieval latency_ms must be greater than or equal to 0")


@dataclass(frozen=True, slots=True)
class WarningMessage:
    code: ErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class QueryAnswer:
    answer_text: str
    sql_text: str
    table_result: TableResult
    trace_id: str
    chart_spec: ChartSpec | None = None
    analytics_result: Mapping[str, Any] | None = None
    evidence_list: tuple[EvidenceItem, ...] = ()
    evidence_uncertainty: bool = False
    retrieval_stats: RetrievalStats | None = None
    confidence: float = 1.0
    warnings: tuple[WarningMessage, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    decision: GuardrailDecision
    trace_id: str
    safe_sql: str | None = None
    error_code: ErrorCode | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.decision is GuardrailDecision.ALLOW and self.safe_sql is None:
            raise ValueError("allowed guardrail result must include safe_sql")
        if self.decision is GuardrailDecision.DENY and self.error_code is None:
            raise ValueError("denied guardrail result must include error_code")


@dataclass(frozen=True, slots=True)
class AgentTraceEvent:
    trace_id: str
    agent_name: AgentName
    status: AgentStepStatus
    occurred_at: datetime
    duration_ms: int | None = None
    summary: str | None = None
    agent_trace_id: str = field(default_factory=new_agent_trace_id)


@dataclass(frozen=True, slots=True)
class QueryHistoryRecord:
    trace_id: str
    request: QueryRequest
    answer: QueryAnswer | None
    created_at: datetime = field(default_factory=utc_now)
    failed_error_code: ErrorCode | None = None
    status: QueryHistoryStatus = field(init=False)
    sql_text: str | None = field(init=False)

    def __post_init__(self) -> None:
        status = (
            QueryHistoryStatus.FAILED
            if self.failed_error_code is not None
            else QueryHistoryStatus.SUCCEEDED
        )
        sql_text = self.answer.sql_text if self.answer is not None else None
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "sql_text", sql_text)


@dataclass(frozen=True, slots=True)
class TraceLinkedRecord:
    trace_id: str
    record_type: TraceLinkedRecordType
    record_id: str

    def __post_init__(self) -> None:
        if not self.trace_id.strip():
            raise ValueError("trace_id is required")
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")
        if not self.record_id.strip():
            raise ValueError("record_id is required")


def build_trace_linked_records(
    trace_id: str,
    message_id: str,
    query_result_id: str,
    agent_trace_id: str,
    audit_event_id: str,
    eval_score_id: str,
) -> tuple[TraceLinkedRecord, ...]:
    return (
        TraceLinkedRecord(
            trace_id=trace_id,
            record_type=TraceLinkedRecordType.MESSAGE,
            record_id=message_id,
        ),
        TraceLinkedRecord(
            trace_id=trace_id,
            record_type=TraceLinkedRecordType.QUERY_RESULT,
            record_id=query_result_id,
        ),
        TraceLinkedRecord(
            trace_id=trace_id,
            record_type=TraceLinkedRecordType.AGENT_TRACE,
            record_id=agent_trace_id,
        ),
        TraceLinkedRecord(
            trace_id=trace_id,
            record_type=TraceLinkedRecordType.AUDIT_EVENT,
            record_id=audit_event_id,
        ),
        TraceLinkedRecord(
            trace_id=trace_id,
            record_type=TraceLinkedRecordType.EVAL_SCORE,
            record_id=eval_score_id,
        ),
    )


class OrchestratorPort(Protocol):
    def answer(self, request: QueryRequest, trace_id: str) -> QueryAnswer:
        """Route the request through agents and return one final answer."""
        ...


class GuardrailPort(Protocol):
    def check(self, sql_text: str, request: QueryRequest, trace_id: str) -> GuardrailResult:
        """Validate SQL before any database execution."""
        ...


class QueryHistoryPort(Protocol):
    def save(self, record: QueryHistoryRecord) -> None:
        """Persist successful and failed requests for replay."""
        ...

    def get(self, trace_id: str) -> QueryHistoryRecord | None:
        """Load one request by trace id."""
        ...


def low_confidence_warning(confidence: float) -> WarningMessage | None:
    if confidence >= 0.6:
        return None
    return WarningMessage(
        code=ErrorCode.LOW_CONFIDENCE,
        message="Answer confidence is below 0.60; human review is recommended.",
    )


def ensure_required_answer_fields(answer: QueryAnswer) -> None:
    """Runtime assertion for FR-01-002 and the traceability constraint."""

    if not answer.answer_text.strip():
        raise ValueError("answer_text is required")
    if not answer.sql_text.strip():
        raise ValueError("sql_text is required")
    if not answer.table_result.columns:
        raise ValueError("table_result.columns is required")
    if not answer.trace_id.strip():
        raise ValueError("trace_id is required")
