"""API-facing models for the Backend API contract.

These dataclasses describe the public REST payloads. The HTTP layer can stay
thin because all response shapes are named here in one place.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4

from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog
from chatbi.core.contracts import (
    ChartSpec,
    ErrorCode,
    EvidenceItem,
    Locale,
    QueryAnswer,
    QueryHistoryRecord,
    QueryHistoryStatus,
    QueryRequest,
    RetrievalStats,
    TableResult,
    UserRole,
    WarningMessage,
)
from chatbi.observability import AlertEvent, ObservabilitySpan, SloStatus, TraceReplay


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_eval_run_id() -> str:
    return f"eval_{uuid4().hex}"


class ApiErrorCode(StrEnum):
    AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    REQ_INVALID_ARGUMENT = "REQ_INVALID_ARGUMENT"
    SQL_GUARDRAIL_BLOCKED = "SQL_GUARDRAIL_BLOCKED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    AGENT_PARTIAL_FAILURE = "AGENT_PARTIAL_FAILURE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ChatQueryRequestPayload:
    user_id: str
    session_id: str
    question: str
    locale: Locale
    role: UserRole

    def to_domain(self) -> QueryRequest:
        return QueryRequest(
            user_id=self.user_id,
            session_id=self.session_id,
            question=self.question,
            locale=self.locale,
            role=self.role,
        )


@dataclass(frozen=True, slots=True)
class ChatQueryResponsePayload:
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


@dataclass(frozen=True, slots=True)
class ApiEnvelope:
    code: int | ApiErrorCode
    message: str
    data: Mapping[str, Any] | None
    trace_id: str
    request_id: str
    warnings: tuple[WarningMessage, ...] = ()
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class HistoryItemPayload:
    trace_id: str
    session_id: str
    question: str
    status: QueryHistoryStatus
    created_at: str
    answer_text: str | None = None
    sql_text: str | None = None
    error_code: ErrorCode | None = None


@dataclass(frozen=True, slots=True)
class CursorPagePayload:
    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    page_size: int


@dataclass(frozen=True, slots=True)
class TraceDetailPayload:
    trace_id: str
    request: Mapping[str, Any]
    answer: Mapping[str, Any] | None
    status: QueryHistoryStatus
    created_at: str
    failed_error_code: ErrorCode | None = None


@dataclass(frozen=True, slots=True)
class ObservabilitySpanPayload:
    trace_id: str
    span_name: str
    status: str
    occurred_at: str
    duration_ms: int | None
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ObservabilityTracePayload:
    trace_id: str
    completed: bool
    spans: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class AuditRecordPayload:
    trace_id: str
    user_id: str
    endpoint: str
    status_code: int
    recorded_at: str
    error_code: ApiErrorCode | None = None


@dataclass(frozen=True, slots=True)
class DatasetColumnPayload:
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool
    sensitivity: str | None = None
    foreign_key: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetPayload:
    name: str
    domain: str
    columns: tuple[Mapping[str, Any], ...]
    partition_column: str | None
    indexes: tuple[tuple[str, ...], ...]
    retention_days: int | None


@dataclass(frozen=True, slots=True)
class EvalRunRequestPayload:
    eval_suite_id: str
    questions: tuple[str, ...]
    locale: Locale
    role: UserRole


@dataclass(frozen=True, slots=True)
class EvalCaseResultPayload:
    question: str
    trace_id: str
    passed: bool
    score: float
    confidence: float
    error_code: ApiErrorCode | None = None


@dataclass(frozen=True, slots=True)
class EvalRunResultPayload:
    eval_run_id: str
    eval_suite_id: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    overall_score: float
    average_confidence: float
    metric_breakdown: Mapping[str, float]
    failed_cases_detail: tuple[Mapping[str, Any], ...]
    release_gate_passed: bool


@dataclass(frozen=True, slots=True)
class SloStatusPayload:
    rule_id: str
    endpoint: str
    target: float
    observed_value: float
    passing: bool
    sample_count: int


@dataclass(frozen=True, slots=True)
class AlertEventPayload:
    rule_id: str
    endpoint: str
    severity: str
    observed_value: float
    threshold: float
    window_minutes: int
    sample_count: int
    message: str


@dataclass(frozen=True, slots=True)
class ReleaseGateSummaryPayload:
    eval_run_id: str
    eval_suite_id: str
    overall_score: float
    release_gate_passed: bool


@dataclass(frozen=True, slots=True)
class QualityDashboardPayload:
    slo_statuses: tuple[Mapping[str, Any], ...]
    alerts: tuple[Mapping[str, Any], ...]
    release_gate: Mapping[str, Any] | None
    active_slo_count: int


def to_chat_query_response(answer: QueryAnswer) -> ChatQueryResponsePayload:
    return ChatQueryResponsePayload(
        answer_text=answer.answer_text,
        sql_text=answer.sql_text,
        table_result=answer.table_result,
        trace_id=answer.trace_id,
        chart_spec=answer.chart_spec,
        analytics_result=answer.analytics_result,
        evidence_list=answer.evidence_list,
        evidence_uncertainty=answer.evidence_uncertainty,
        retrieval_stats=answer.retrieval_stats,
        confidence=answer.confidence,
        warnings=answer.warnings,
    )


def success_envelope(response: ChatQueryResponsePayload) -> ApiEnvelope:
    return envelope(
        data={
            "answer_text": response.answer_text,
            "sql_text": response.sql_text,
            "table_result": response.table_result,
            "chart_spec": response.chart_spec,
            "analytics_result": response.analytics_result,
            "evidence_list": response.evidence_list,
            "evidence_uncertainty": response.evidence_uncertainty,
            "retrieval_stats": response.retrieval_stats,
            "confidence": response.confidence,
        },
        trace_id=response.trace_id,
        warnings=response.warnings,
    )


def request_id_from_trace_id(trace_id: str) -> str:
    if trace_id.startswith("trc_"):
        return f"req_{trace_id.removeprefix('trc_')}"
    if trace_id.startswith("tr_"):
        return f"req_{trace_id.removeprefix('tr_')}"
    return f"req_{trace_id}"


def envelope(
    data: Mapping[str, Any] | None,
    trace_id: str,
    warnings: tuple[WarningMessage, ...] = (),
    request_id: str | None = None,
) -> ApiEnvelope:
    return ApiEnvelope(
        code=0,
        message="ok",
        data=data,
        trace_id=trace_id,
        request_id=request_id or request_id_from_trace_id(trace_id),
        warnings=warnings,
    )


def error_envelope(
    code: ApiErrorCode,
    message: str,
    trace_id: str,
    data: Mapping[str, Any] | None = None,
    warnings: tuple[WarningMessage, ...] = (),
    request_id: str | None = None,
) -> ApiEnvelope:
    return ApiEnvelope(
        code=code,
        message=message,
        data=data,
        trace_id=trace_id,
        request_id=request_id or request_id_from_trace_id(trace_id),
        warnings=warnings,
    )


def api_error_for_warning(warning: WarningMessage) -> ApiErrorCode:
    if warning.code in {
        ErrorCode.SQL_DENY_STATEMENT,
        ErrorCode.SQL_DENY_OBJECT,
        ErrorCode.SQL_DENY_FUNCTION,
    }:
        return ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    if warning.code is ErrorCode.QUERY_TIMEOUT:
        return ApiErrorCode.QUERY_TIMEOUT
    if warning.code is ErrorCode.AGENT_PARTIAL_FAILURE:
        return ApiErrorCode.AGENT_PARTIAL_FAILURE
    return ApiErrorCode.INTERNAL_ERROR


def history_item_payload(record: QueryHistoryRecord) -> HistoryItemPayload:
    return HistoryItemPayload(
        trace_id=record.trace_id,
        session_id=record.request.session_id,
        question=record.request.question,
        status=record.status,
        created_at=record.created_at.isoformat(),
        answer_text=record.answer.answer_text if record.answer is not None else None,
        sql_text=record.sql_text,
        error_code=record.failed_error_code,
    )


def trace_detail_payload(record: QueryHistoryRecord) -> TraceDetailPayload:
    return TraceDetailPayload(
        trace_id=record.trace_id,
        request={
            "user_id": record.request.user_id,
            "session_id": record.request.session_id,
            "question": record.request.question,
            "locale": record.request.locale,
            "role": record.request.role,
        },
        answer=_answer_data(record.answer) if record.answer is not None else None,
        status=record.status,
        created_at=record.created_at.isoformat(),
        failed_error_code=record.failed_error_code,
    )


def observability_span_payload(span: ObservabilitySpan) -> ObservabilitySpanPayload:
    return ObservabilitySpanPayload(
        trace_id=span.trace_id,
        span_name=span.span_name.value,
        status=span.status.value,
        occurred_at=span.occurred_at.isoformat(),
        duration_ms=span.duration_ms,
        attributes=span.attributes,
    )


def observability_trace_payload(replay: TraceReplay) -> ObservabilityTracePayload:
    return ObservabilityTracePayload(
        trace_id=replay.trace_id,
        completed=replay.completed,
        spans=tuple(asdict(observability_span_payload(span)) for span in replay.spans),
    )


def slo_status_payload(status: SloStatus) -> SloStatusPayload:
    return SloStatusPayload(
        rule_id=status.rule_id.value,
        endpoint=status.endpoint,
        target=status.target,
        observed_value=status.observed_value,
        passing=status.passing,
        sample_count=status.sample_count,
    )


def alert_event_payload(alert: AlertEvent) -> AlertEventPayload:
    return AlertEventPayload(
        rule_id=alert.rule_id.value,
        endpoint=alert.endpoint,
        severity=alert.severity.value,
        observed_value=alert.observed_value,
        threshold=alert.threshold,
        window_minutes=alert.window_minutes,
        sample_count=alert.sample_count,
        message=alert.message,
    )


def release_gate_summary_payload(
    result: EvalRunResultPayload,
) -> ReleaseGateSummaryPayload:
    return ReleaseGateSummaryPayload(
        eval_run_id=result.eval_run_id,
        eval_suite_id=result.eval_suite_id,
        overall_score=result.overall_score,
        release_gate_passed=result.release_gate_passed,
    )


def quality_dashboard_payload(
    slo_statuses: tuple[SloStatus, ...],
    alerts: tuple[AlertEvent, ...],
    latest_eval_result: EvalRunResultPayload | None,
) -> QualityDashboardPayload:
    release_gate = (
        asdict(release_gate_summary_payload(latest_eval_result))
        if latest_eval_result is not None
        else None
    )
    return QualityDashboardPayload(
        slo_statuses=tuple(asdict(slo_status_payload(status)) for status in slo_statuses),
        alerts=tuple(asdict(alert_event_payload(alert)) for alert in alerts),
        release_gate=release_gate,
        active_slo_count=len(slo_statuses),
    )


def metrics_catalog_payload(
    catalog: DataModelCatalog | None = None,
) -> tuple[Mapping[str, Any], ...]:
    active_catalog = catalog or build_default_data_model_catalog()
    metrics: list[Mapping[str, Any]] = []
    for metric_name in active_catalog.metric_names():
        metric = active_catalog.get_metric(metric_name)
        if metric is None:
            continue
        metrics.append(
            {
                "id": metric.metric_id,
                "name": metric.name,
                "formula": metric.formula,
                "owner": metric.owner,
                "status": metric.status,
                "sql_definition": metric.sql_definition,
                "source_tables": metric.source_tables,
                "semantic_version": metric.semantic_version,
                "semantic_version_id": metric.semantic_version_id,
            }
        )
    return tuple(metrics)


def datasets_catalog_payload(
    catalog: DataModelCatalog | None = None,
) -> tuple[Mapping[str, Any], ...]:
    active_catalog = catalog or build_default_data_model_catalog()
    datasets: list[Mapping[str, Any]] = []
    for table_name in active_catalog.table_names():
        table = active_catalog.get_table(table_name)
        if table is None:
            continue

        columns = tuple(
            {
                "name": column.name,
                "data_type": column.data_type,
                "nullable": column.nullable,
                "is_primary_key": column.is_primary_key,
                "sensitivity": column.sensitivity.value if column.sensitivity is not None else None,
                "foreign_key": column.foreign_key,
            }
            for column in table.columns
        )
        datasets.append(
            {
                "name": table.name,
                "domain": table.domain.value,
                "columns": columns,
                "partition_column": table.partition_column,
                "indexes": table.indexes,
                "retention_days": table.retention_days,
            }
        )
    return tuple(datasets)


def _answer_data(answer: QueryAnswer) -> Mapping[str, Any]:
    response = to_chat_query_response(answer)
    return {
        "answer_text": response.answer_text,
        "sql_text": response.sql_text,
        "table_result": response.table_result,
        "chart_spec": response.chart_spec,
        "analytics_result": response.analytics_result,
        "evidence_list": response.evidence_list,
        "confidence": response.confidence,
    }
