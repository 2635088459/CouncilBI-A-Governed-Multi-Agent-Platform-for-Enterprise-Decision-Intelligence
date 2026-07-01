"""FastAPI entry point for the Backend API slice."""

from __future__ import annotations

from hashlib import sha256
import os
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Mapping, Sequence, cast
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from chatbi.analytics import (
    AnalyticsGrain,
    AnalyticsOptions,
    AnalyticsRequest,
    AnalyticsService,
    AnalyticsValidationError,
    result_to_dict,
)
from chatbi.analytics_repository import InMemoryAnalyticsRepository
from chatbi.api.models import (
    ApiEnvelope,
    ApiErrorCode,
    ChatQueryRequestPayload,
    EvalRunRequestPayload,
    envelope,
    error_envelope,
)
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import Locale, QueryRequest, UserRole, new_trace_id
from chatbi.core.runtime_config import (
    DatabaseReadinessChecker,
    RedisReadinessChecker,
    RedisTcpPingClient,
    RuntimeConfig,
    load_runtime_config,
)
from chatbi.core.architecture_contracts import (
    AnswerPayloadV2,
    ChatQueryResponseV2,
    ErrorPayloadV2,
    EvidenceItemV2,
    TableResultV2,
    validate_chat_query_request_v2,
    validation_error_response_v2,
)
from chatbi.history.request_metadata import (
    build_request_metadata_store,
    connect_psycopg,
    InMemoryRequestMetadataStore,
    RequestMetadataRecord,
    RequestMetadataStore,
)
from chatbi.history.query_results import (
    RuntimeQueryResultRecord,
    RuntimeQueryResultStore,
    postgres_runtime_query_result_store_from_psycopg,
)
from chatbi.governance import (
    GuardrailAuditLogV2,
    GuardrailDecisionV2,
    GuardrailRequestV2,
    ReadOnlyDatabaseProbe,
    ReadOnlyDatabaseProbeRunner,
    ReadOnlyQueryExecutor,
    SimpleSqlGuardrailV2,
    postgres_guardrail_audit_log_v2_from_psycopg,
)
from chatbi.observability_logs import LogLevel, ObservabilityLogger
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator
from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRecord,
    AsyncTaskRequest,
    InMemoryWorkerHandoffQueue,
    WorkerHandoffQueue,
)
from chatbi.runtime_metrics import RuntimeMetricsSnapshot, render_runtime_metrics
from chatbi.semantic import SemanticNl2SqlPipeline, SemanticResolveResponse, SemanticResolveStatus


# Request body models translate HTTP JSON into API contract dataclasses.
class ChatQueryRequestBody(BaseModel):
    user_id: str
    session_id: str
    question: str
    locale: Locale
    role: UserRole

    def to_payload(self) -> ChatQueryRequestPayload:
        return ChatQueryRequestPayload(
            user_id=self.user_id,
            session_id=self.session_id,
            question=self.question,
            locale=self.locale,
            role=self.role,
        )


class EvalRunRequestBody(BaseModel):
    eval_suite_id: str = "backend_api_smoke"
    questions: tuple[str, ...] = ()
    locale: Locale = Locale.EN
    role: UserRole = UserRole.ANALYST

    def to_payload(self) -> EvalRunRequestPayload:
        return EvalRunRequestPayload(
            eval_suite_id=self.eval_suite_id,
            questions=self.questions,
            locale=self.locale,
            role=self.role,
        )


class AnalyticsOptionsBody(BaseModel):
    horizon: int = 3
    anomaly_z_threshold: float = 3.0

    def to_domain(self) -> AnalyticsOptions:
        return AnalyticsOptions(
            horizon=self.horizon,
            anomaly_z_threshold=self.anomaly_z_threshold,
        )


class AnalyticsRequestBody(BaseModel):
    trace_id: str
    metric_id: str
    semantic_version_id: str
    time_column: str
    value_column: str
    grain: AnalyticsGrain
    rows: tuple[dict[str, Any], ...]
    analysis_options: AnalyticsOptionsBody = AnalyticsOptionsBody()

    def to_domain(self) -> AnalyticsRequest:
        return AnalyticsRequest(
            trace_id=self.trace_id,
            metric_id=self.metric_id,
            semantic_version_id=self.semantic_version_id,
            time_column=self.time_column,
            value_column=self.value_column,
            grain=self.grain,
            rows=self.rows,
            analysis_options=self.analysis_options.to_domain(),
        )

    def to_task_payload(self) -> Mapping[str, object]:
        return {
            "trace_id": self.trace_id,
            "metric_id": self.metric_id,
            "semantic_version_id": self.semantic_version_id,
            "time_column": self.time_column,
            "value_column": self.value_column,
            "grain": self.grain.value,
            "rows": self.rows,
            "analysis_options": {
                "horizon": self.analysis_options.horizon,
                "anomaly_z_threshold": self.analysis_options.anomaly_z_threshold,
            },
        }


class DocumentIndexRequestBody(BaseModel):
    document_id: str
    source: str
    title: str
    document_type: str
    published_at: str
    business_tags: tuple[str, ...] = ()
    permission_tags: tuple[str, ...] = ()
    text: str

    def validation_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        for field_name in ("document_id", "source", "title", "published_at"):
            if not str(getattr(self, field_name)).strip():
                errors.append(f"{field_name} is required.")
        if self.document_type not in {
            "weekly_report",
            "release_note",
            "campaign",
            "ticket",
            "incident",
            "finance_report",
        }:
            errors.append("document_type is not supported.")
        text_length = len(self.text)
        if text_length < 1 or text_length > 500_000:
            errors.append("text length must be between 1 and 500000 characters.")
        return tuple(errors)

    def to_task_payload(self) -> Mapping[str, object]:
        return {
            "document_id": self.document_id,
            "source": self.source,
            "title": self.title,
            "document_type": self.document_type,
            "published_at": self.published_at,
            "business_tags": self.business_tags,
            "permission_tags": self.permission_tags,
            "text": self.text,
            "text_length": len(self.text),
        }

    def idempotency_fingerprint(self) -> tuple[tuple[str, str], ...]:
        return (
            ("business_tags", ",".join(self.business_tags)),
            ("document_id", self.document_id),
            ("document_type", self.document_type),
            ("permission_tags", ",".join(self.permission_tags)),
            ("published_at", self.published_at),
            ("source", self.source),
            ("text_sha256", sha256(self.text.encode("utf-8")).hexdigest()),
            ("title", self.title),
        )


class SqlPreviewRequestBody(BaseModel):
    user_id: str
    question: str
    locale: Locale
    role: UserRole
    session_id: str = "s_sql_preview"

    def to_query_request(self) -> QueryRequest:
        return QueryRequest(
            user_id=self.user_id,
            session_id=self.session_id,
            question=self.question,
            locale=self.locale,
            role=self.role,
        )


class SqlGuardrailCheckRequestBody(BaseModel):
    user_id: str
    role: UserRole
    sql_text: str
    semantic_version_id: str

    def to_guardrail_request(self, trace_id: str) -> GuardrailRequestV2:
        return GuardrailRequestV2(
            trace_id=trace_id,
            user_id=self.user_id,
            role=self.role.value,
            sql_text=self.sql_text,
            semantic_version_id=self.semantic_version_id,
        )


class SemanticResolveRequestBody(BaseModel):
    user_id: str
    question: str
    locale: Locale
    role: UserRole
    session_id: str = "s_semantic_resolve"

    def to_query_request(self) -> QueryRequest:
        return QueryRequest(
            user_id=self.user_id,
            session_id=self.session_id,
            question=self.question,
            locale=self.locale,
            role=self.role,
        )


@dataclass(frozen=True, slots=True)
class DocumentIndexIdempotencyEntry:
    body_fingerprint: tuple[tuple[str, str], ...]
    task: AsyncTaskRecord


# Response helpers keep every endpoint on the unified envelope contract.
def envelope_to_dict(envelope: ApiEnvelope) -> dict[str, Any]:
    return asdict(envelope)


def response_from_envelope(envelope: ApiEnvelope, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=envelope_to_dict(envelope),
    )


def status_code_for_envelope(envelope: ApiEnvelope) -> int:
    if envelope.code is ApiErrorCode.RATE_LIMITED:
        return 429
    if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT:
        return 400
    if envelope.code is ApiErrorCode.AUTH_UNAUTHORIZED:
        return 401
    if envelope.code is ApiErrorCode.AUTH_FORBIDDEN:
        return 403
    return 200


def runtime_dependency_status(env: Mapping[str, str] | None = None) -> dict[str, dict[str, bool]]:
    """Read deployment dependency wiring for runtime probes.

    Kubernetes readiness is about traffic safety: if a required dependency is
    not configured, the pod should not receive user traffic yet.
    """

    return load_runtime_config(env).dependency_status()


def is_runtime_ready(env: Mapping[str, str] | None = None) -> bool:
    return load_runtime_config(env).ready_for_traffic


def metrics_text(
    env: Mapping[str, str] | None = None,
    runtime_metrics: RuntimeMetricsSnapshot | None = None,
) -> str:
    config = load_runtime_config(env)
    ready_value = 1 if config.ready_for_traffic else 0
    return "\n".join(
        (
            "# HELP chatbi_api_info Static service identity for the ChatBI API.",
            "# TYPE chatbi_api_info gauge",
            f'chatbi_api_info{{service="{config.service_name}"}} 1',
            "# HELP chatbi_api_ready Readiness state for user traffic.",
            "# TYPE chatbi_api_ready gauge",
            f"chatbi_api_ready {ready_value}",
            render_runtime_metrics(runtime_metrics),
            "",
        )
    )


def use_postgres_metadata_from_env(env: Mapping[str, str] | None = None) -> bool:
    runtime_env = env or os.environ
    return runtime_env.get("CHATBI_USE_POSTGRES_METADATA", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _build_default_request_metadata_store(
    runtime_config: RuntimeConfig,
    connect: Callable[[str], Any] | None,
    use_postgres_metadata: bool,
) -> RequestMetadataStore:
    if use_postgres_metadata:
        return build_request_metadata_store(
            runtime_config=runtime_config,
            connect=connect or connect_psycopg,
        )
    return InMemoryRequestMetadataStore()


def _build_default_guardrail_audit_log_v2(
    runtime_config: RuntimeConfig,
    connect: Callable[[str], Any] | None,
    use_postgres_metadata: bool,
) -> GuardrailAuditLogV2 | None:
    if not use_postgres_metadata or runtime_config.database_url is None:
        return None

    raw_connection = (connect or connect_psycopg)(runtime_config.database_url)
    store = postgres_guardrail_audit_log_v2_from_psycopg(raw_connection)
    store.initialize_schema()
    return store


def _build_default_runtime_query_result_store(
    runtime_config: RuntimeConfig,
    connect: Callable[[str], Any] | None,
    use_postgres_metadata: bool,
) -> RuntimeQueryResultStore | None:
    if not use_postgres_metadata or runtime_config.database_url is None:
        return None

    store = postgres_runtime_query_result_store_from_psycopg(
        (connect or connect_psycopg)(runtime_config.database_url)
    )
    store.initialize_schema()
    return store


def _build_default_chatbi_application(
    runtime_config: RuntimeConfig,
    readonly_query_connect: Callable[[str], Any] | None = None,
) -> ChatBIApplication:
    if runtime_config.readonly_database_url is None:
        return ChatBIApplication()

    return ChatBIApplication(
        orchestrator=SimpleOrchestrator(
            readonly_query_executor=ReadOnlyQueryExecutor(
                readonly_query_connect or connect_psycopg,
            ),
            readonly_database_url=runtime_config.readonly_database_url,
        )
    )


def database_readiness_checker_from_env(
    env: Mapping[str, str] | None = None,
) -> DatabaseReadinessChecker | None:
    if not use_postgres_metadata_from_env(env):
        return None
    return DatabaseReadinessChecker(connect_psycopg)


def readonly_database_probe_from_env(
    env: Mapping[str, str] | None = None,
) -> ReadOnlyDatabaseProbeRunner | None:
    runtime_env = env or os.environ
    if not runtime_env.get("CHATBI_READONLY_DATABASE_URL", "").strip():
        return None
    return ReadOnlyDatabaseProbe(connect_psycopg)


def redis_readiness_checker_from_env(
    env: Mapping[str, str] | None = None,
) -> RedisReadinessChecker | None:
    runtime_env = env or os.environ
    if not runtime_env.get("REDIS_URL", "").strip():
        return None
    return RedisReadinessChecker(lambda redis_url: RedisTcpPingClient(redis_url))


def request_metadata_to_dict(record: RequestMetadataRecord) -> dict[str, Any]:
    return {
        "trace_id": record.trace_id,
        "request_id": record.request_id,
        "session_id": record.session_id,
        "user_id": record.user_id,
        "role": record.role.value,
        "locale": record.locale.value,
        "question": record.question,
        "status": record.status.value,
        "accepted_at": record.accepted_at.isoformat(),
        "finished_at": record.finished_at.isoformat() if record.finished_at is not None else None,
        "error_code": record.error_code,
    }


def runtime_query_result_record_from_response(
    *,
    trace_id: str,
    session_id: str,
    user_id: str,
    question: str,
    data: object,
) -> RuntimeQueryResultRecord | None:
    if not isinstance(data, Mapping):
        return None

    data_mapping = cast(Mapping[str, object], data)
    sql_text = data_mapping.get("sql_text")
    table_result = data_mapping.get("table_result")
    chart_spec = data_mapping.get("chart_spec")
    if not isinstance(sql_text, str):
        return None

    table_result_mapping = _mapping_for_runtime_json(table_result)
    if table_result_mapping is None:
        return None

    return RuntimeQueryResultRecord(
        trace_id=trace_id,
        session_id=session_id,
        user_id=user_id,
        question=question,
        sql_text=sql_text,
        table_result=table_result_mapping,
        chart_spec=_mapping_for_runtime_json(chart_spec),
    )


def _mapping_for_runtime_json(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return None


def runtime_query_result_to_dict(record: RuntimeQueryResultRecord) -> dict[str, object]:
    return {
        "trace_id": record.trace_id,
        "session_id": record.session_id,
        "user_id": record.user_id,
        "question": record.question,
        "sql_hash": record.sql_hash,
        "table_result": record.table_result,
        "chart_spec": record.chart_spec,
        "created_at": record.created_at.isoformat() if record.created_at is not None else None,
    }


def async_task_record_to_dict(record: object) -> dict[str, object]:
    """Serialize the worker task record without exposing queue internals."""

    payload = dict(cast(Mapping[str, object], getattr(record, "payload")))
    if "text" in payload:
        payload = {key: value for key, value in payload.items() if key != "text"}
        payload["text_redacted"] = True
    return {
        "task_id": getattr(record, "task_id"),
        "trace_id": getattr(record, "trace_id"),
        "kind": getattr(getattr(record, "kind"), "value"),
        "status": getattr(getattr(record, "status"), "value"),
        "payload": payload,
        "result": dict(cast(Mapping[str, object], getattr(record, "result", {}))),
        "error_message": getattr(record, "error_message", None),
    }


def document_index_response_data(
    body: DocumentIndexRequestBody,
    task: AsyncTaskRecord,
) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "trace_id": task.trace_id,
        "kind": task.kind.value,
        "status": task.status.value,
        "document_id": body.document_id,
        "document_type": body.document_type,
        "text_length": len(body.text),
        "async": True,
    }


def guardrail_audit_record_to_dict(record: object | None) -> dict[str, object]:
    if record is None:
        return {"exists": False}

    rule_hits = getattr(record, "rule_hits", ())
    occurred_at = getattr(record, "occurred_at", None)
    return {
        "exists": True,
        "trace_id": getattr(record, "trace_id", None),
        "user_id": getattr(record, "user_id", None),
        "role": getattr(record, "role", None),
        "sql_hash": getattr(record, "sql_hash", None),
        "decision": getattr(getattr(record, "decision", None), "value", None),
        "latency_ms": getattr(record, "latency_ms", None),
        "rule_hits": [
            {
                "rule_code": getattr(rule_hit.rule_code, "value", str(rule_hit.rule_code)),
                "message": rule_hit.message,
                "object_name": rule_hit.object_name,
            }
            for rule_hit in rule_hits
        ],
        "created_at": _isoformat_or_none(occurred_at),
    }


def governance_trace_summary(
    *,
    trace_id: str,
    request_record: RequestMetadataRecord | None,
    query_result_record: RuntimeQueryResultRecord | None,
    guardrail_record: object | None,
) -> dict[str, object]:
    return {
        "trace_id": trace_id,
        "request": (
            {
                "exists": True,
                "status": request_record.status.value,
                "request_id": request_record.request_id,
                "session_id": request_record.session_id,
                "user_id": request_record.user_id,
                "role": request_record.role.value,
                "locale": request_record.locale.value,
                "accepted_at": request_record.accepted_at.isoformat(),
                "finished_at": (
                    request_record.finished_at.isoformat()
                    if request_record.finished_at is not None
                    else None
                ),
                "error_code": request_record.error_code,
            }
            if request_record is not None
            else {"exists": False}
        ),
        "query_result": _governance_query_result_summary(query_result_record),
        "guardrail": guardrail_audit_record_to_dict(guardrail_record),
    }


def _governance_query_result_summary(
    record: RuntimeQueryResultRecord | None,
) -> dict[str, object]:
    if record is None:
        return {"exists": False}

    return {
        "exists": True,
        "trace_id": record.trace_id,
        "session_id": record.session_id,
        "user_id": record.user_id,
        "sql_hash": record.sql_hash,
        "row_count": _table_result_row_count(record.table_result),
        "has_chart": record.chart_spec is not None,
        "created_at": record.created_at.isoformat() if record.created_at is not None else None,
    }


def _table_result_row_count(table_result: Mapping[str, object]) -> int:
    rows = table_result.get("rows")
    if isinstance(rows, list | tuple):
        return len(cast(Sequence[object], rows))
    return 0


def _isoformat_or_none(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def new_trace_id_v2() -> str:
    return f"tr_{uuid4().hex}"


def legacy_trace_id_from_v2(trace_id: str) -> str:
    """Bridge the v2 public trace id to the current internal trace prefix."""

    return f"trc_{trace_id.removeprefix('tr_')}"


def public_trace_id_from_legacy(trace_id: str) -> str:
    """Bridge the current internal trace prefix back to the v2 public prefix."""

    if trace_id.startswith("trc_"):
        return f"tr_{trace_id.removeprefix('trc_')}"
    return trace_id


def v2_request_id_from_body(body: dict[str, Any]) -> str:
    request_id = body.get("request_id")
    if isinstance(request_id, str) and request_id.startswith("req_"):
        return request_id
    return "req_invalid_request"


def v2_request_id_from_header(value: str | None, fallback: str) -> str:
    if isinstance(value, str) and value.startswith("req_"):
        return value
    return fallback


def v2_error_response(
    *,
    request_id: str,
    trace_id: str,
    code: str,
    message: str,
    status_code: int,
    retryable: bool = False,
) -> JSONResponse:
    response: ChatQueryResponseV2 = {
        "trace_id": trace_id,
        "request_id": request_id,
        "data": None,
        "warnings": [
            {
                "code": code,
                "message": message,
            }
        ],
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
    return JSONResponse(status_code=status_code, content=response)


def v2_response_from_api_envelope(
    api_envelope: ApiEnvelope,
    *,
    request_id: str,
    trace_id: str,
) -> ChatQueryResponseV2:
    data = _v2_answer_payload(api_envelope.data)
    error: ErrorPayloadV2 | None = None
    if api_envelope.code != 0:
        error = {
            "code": str(api_envelope.code),
            "message": api_envelope.message,
            "retryable": api_envelope.code is ApiErrorCode.RATE_LIMITED,
        }

    return {
        "trace_id": trace_id,
        "request_id": request_id,
        "data": data,
        "warnings": [
            {
                "code": str(warning.code),
                "message": warning.message,
            }
            for warning in api_envelope.warnings
        ],
        "error": error,
    }


def v2_generic_response_from_api_envelope(
    api_envelope: ApiEnvelope,
    *,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    error: ErrorPayloadV2 | None = None
    if api_envelope.code != 0:
        error = {
            "code": str(api_envelope.code),
            "message": api_envelope.message,
            "retryable": api_envelope.code is ApiErrorCode.RATE_LIMITED,
        }

    return {
        "trace_id": trace_id,
        "request_id": request_id,
        "data": api_envelope.data,
        "warnings": [
            {
                "code": str(warning.code),
                "message": warning.message,
            }
            for warning in api_envelope.warnings
        ],
        "error": error,
    }


def v2_history_data(data: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if data is None:
        return None

    items = data.get("items")
    if not isinstance(items, tuple | list):
        return data

    public_items: list[Mapping[str, Any]] = []
    for item in cast(Sequence[object], items):
        if not isinstance(item, Mapping):
            public_items.append({"value": item})
            continue
        public_item = dict(cast(Mapping[str, Any], item))
        trace_id = public_item.get("trace_id")
        if isinstance(trace_id, str):
            public_item["trace_id"] = public_trace_id_from_legacy(trace_id)
        public_items.append(public_item)

    return {
        **data,
        "items": public_items,
    }


def v2_query_detail_data(data: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if data is None:
        return None

    public_data = _json_safe_mapping(data)
    trace_id = public_data.get("trace_id")
    if isinstance(trace_id, str):
        public_data["trace_id"] = public_trace_id_from_legacy(trace_id)
    return public_data


def _json_safe_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in data.items()}


def _json_safe_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        return _json_safe_mapping(cast(Mapping[str, Any], value))
    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in cast(Sequence[object], value)]
    return value


def _v2_answer_payload(data: Mapping[str, Any] | None) -> AnswerPayloadV2 | None:
    if data is None:
        return None

    return {
        "answer_text": str(data.get("answer_text", "")),
        "table_result": _v2_table_result(data.get("table_result")),
        "chart_spec": _v2_mapping_or_none(data.get("chart_spec")),
        "evidence_list": [
            _v2_evidence_item(evidence)
            for evidence in _v2_iterable(data.get("evidence_list"))
        ],
        "confidence": float(data.get("confidence", 0.0)),
    }


def _v2_table_result(value: object) -> TableResultV2 | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        mapped = cast(Mapping[str, Any], value)
        return {
            "columns": [str(column) for column in _v2_iterable(mapped.get("columns"))],
            "rows": [_v2_row(row) for row in _v2_iterable(mapped.get("rows"))],
        }
    return {
        "columns": [str(column) for column in _v2_iterable(getattr(value, "columns", ()))],
        "rows": [_v2_row(row) for row in _v2_iterable(getattr(value, "rows", ()))],
    }


def _v2_mapping_or_none(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(cast(Mapping[str, Any], value))
    if is_dataclass(value):
        return asdict(cast(Any, value))
    return {"value": value}


def _v2_evidence_item(value: object) -> EvidenceItemV2:
    if isinstance(value, Mapping):
        raw = cast(Mapping[str, Any], value)
    elif is_dataclass(value):
        raw = asdict(cast(Any, value))
    else:
        raw = {
            "source_id": "unknown",
            "title": "unknown",
            "citation_anchor": "unknown",
            "snippet": str(value),
            "relevance_score": 0.0,
        }
    return {
        "source_id": str(raw.get("source_id", "unknown")),
        "title": str(raw.get("title", "unknown")),
        "citation_anchor": str(raw.get("citation_anchor", "unknown")),
        "snippet": str(raw.get("snippet", "")),
        "relevance_score": float(raw.get("relevance_score", 0.0)),
    }


def _v2_row(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(cast(Mapping[str, Any], value))
    return {"value": value}


def _v2_iterable(value: object) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return cast(tuple[Any, ...], value)
    if isinstance(value, list):
        return tuple(cast(list[Any], value))
    return (value,)


def _semantic_resolution_to_dict(value: SemanticResolveResponse) -> dict[str, Any]:
    time_range = value.time_range
    return {
        "semantic_version_id": value.semantic_version_id,
        "metrics": [asdict(metric) for metric in value.metrics],
        "dimensions": [asdict(dimension) for dimension in value.dimensions],
        "time_range": _time_range_to_dict(time_range),
        "filters": [asdict(filter_ref) for filter_ref in value.filters],
        "status": value.status.value,
        "clarification_question": value.clarification_question,
    }


def _guardrail_decision_to_dict(value: GuardrailDecisionV2) -> dict[str, Any]:
    return {
        "decision": value.decision.value,
        "rewritten_sql": value.rewritten_sql,
        "sql_hash": value.sql_hash,
        "rule_hits": [
            {
                "rule_code": rule_hit.rule_code.value,
                "message": rule_hit.message,
                "object_name": rule_hit.object_name,
            }
            for rule_hit in value.rule_hits
        ],
        "masking_plan": [
            {
                "field_name": instruction.field_name,
                "strategy": instruction.strategy.value,
                "reason": instruction.reason,
            }
            for instruction in value.masking_plan
        ],
        "error": value.error,
    }


def _time_range_to_dict(value: object | None) -> dict[str, str] | None:
    if value is None:
        return None
    start_date = getattr(value, "start_date", None)
    end_date = getattr(value, "end_date", None)
    source = getattr(value, "source", None)
    return {
        "start_date": _isoformat_or_string(start_date),
        "end_date": _isoformat_or_string(end_date),
        "source": str(source),
    }


def _isoformat_or_string(value: Any) -> str:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


# Header validation is the front-door policy for Backend API v1.
def require_headers(
    application: ChatBIApplication,
    endpoint: str,
    trace_id: str | None,
    authorization: str | None,
) -> tuple[str, JSONResponse | None]:
    active_trace_id = trace_id or new_trace_id()
    if trace_id is None or not trace_id.strip():
        envelope = error_envelope(
            code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            message="X-Trace-Id header is required.",
            trace_id=active_trace_id,
        )
        application.record_api_audit(
            trace_id=active_trace_id,
            user_id="anonymous",
            endpoint=endpoint,
            status_code=400,
            error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
        )
        return active_trace_id, response_from_envelope(envelope, status_code=400)

    if authorization is None or not authorization.startswith("Bearer "):
        envelope = error_envelope(
            code=ApiErrorCode.AUTH_UNAUTHORIZED,
            message="Missing or invalid bearer token.",
            trace_id=active_trace_id,
        )
        application.record_api_audit(
            trace_id=active_trace_id,
            user_id="anonymous",
            endpoint=endpoint,
            status_code=401,
            error_code=ApiErrorCode.AUTH_UNAUTHORIZED,
        )
        return active_trace_id, response_from_envelope(envelope, status_code=401)

    return active_trace_id, None


# Route registration is intentionally thin: validate HTTP concerns, call the
# application facade, then serialize one ApiEnvelope back to the client.
def create_app(
    application: ChatBIApplication | None = None,
    runtime_config: RuntimeConfig | None = None,
    request_metadata_store: RequestMetadataStore | None = None,
    request_metadata_connect: Callable[[str], Any] | None = None,
    guardrail_audit_connect: Callable[[str], Any] | None = None,
    runtime_query_result_store: RuntimeQueryResultStore | None = None,
    runtime_query_result_connect: Callable[[str], Any] | None = None,
    readonly_query_connect: Callable[[str], Any] | None = None,
    use_postgres_metadata: bool = False,
    database_readiness_checker: DatabaseReadinessChecker | None = None,
    redis_readiness_checker: RedisReadinessChecker | None = None,
    readonly_database_probe: ReadOnlyDatabaseProbeRunner | None = None,
    observability_logger: ObservabilityLogger | None = None,
    guardrail_audit_log_v2: GuardrailAuditLogV2 | None = None,
    worker_handoff_queue: WorkerHandoffQueue | None = None,
    analytics_service: AnalyticsService | None = None,
) -> FastAPI:
    active_runtime_config = runtime_config or load_runtime_config()
    chatbi_application = application or _build_default_chatbi_application(
        runtime_config=active_runtime_config,
        readonly_query_connect=readonly_query_connect,
    )
    active_request_metadata_store = request_metadata_store or _build_default_request_metadata_store(
        runtime_config=active_runtime_config,
        connect=request_metadata_connect,
        use_postgres_metadata=use_postgres_metadata,
    )
    active_runtime_query_result_store = runtime_query_result_store
    if active_runtime_query_result_store is None and (
        runtime_query_result_connect is not None
        or request_metadata_connect is not None
        or request_metadata_store is None
    ):
        active_runtime_query_result_store = _build_default_runtime_query_result_store(
            runtime_config=active_runtime_config,
            connect=runtime_query_result_connect or request_metadata_connect,
            use_postgres_metadata=use_postgres_metadata,
        )
    active_guardrail_audit_log_v2 = guardrail_audit_log_v2
    if active_guardrail_audit_log_v2 is None and (
        guardrail_audit_connect is not None or request_metadata_connect is None
    ):
        active_guardrail_audit_log_v2 = _build_default_guardrail_audit_log_v2(
            runtime_config=active_runtime_config,
            connect=guardrail_audit_connect,
            use_postgres_metadata=use_postgres_metadata,
        )
    active_observability_logger = observability_logger or ObservabilityLogger()
    active_worker_handoff_queue = worker_handoff_queue or InMemoryWorkerHandoffQueue()
    active_analytics_service = analytics_service or AnalyticsService(
        InMemoryAnalyticsRepository()
    )
    document_index_idempotency_cache: dict[
        tuple[str, ...],
        DocumentIndexIdempotencyEntry,
    ] = {}
    app = FastAPI(title="Governed ChatBI Platform", version="0.1.0")

    def current_readiness_payload() -> tuple[bool, dict[str, object]]:
        dependencies: dict[str, dict[str, object]] = {
            key: dict(value)
            for key, value in active_runtime_config.dependency_status().items()
        }
        if database_readiness_checker is None:
            ready = active_runtime_config.ready_for_traffic
        else:
            ready = database_readiness_checker.is_ready(active_runtime_config.database_url)
            dependencies["postgresql"]["reachable"] = ready
        if redis_readiness_checker is not None:
            redis_ready = redis_readiness_checker.is_ready(active_runtime_config.redis_url)
            dependencies["redis"]["reachable"] = redis_ready
            ready = ready and redis_ready
        if readonly_database_probe is not None:
            readonly_probe_result = readonly_database_probe.check(
                active_runtime_config.readonly_database_url
            )
            dependencies["business_postgresql_readonly"]["write_probe_status"] = (
                readonly_probe_result.status.value
            )
            dependencies["business_postgresql_readonly"]["write_blocked"] = (
                readonly_probe_result.passed
            )
            ready = ready and readonly_probe_result.passed
        return ready, {
            "status": "ready" if ready else "not_ready",
            "service": active_runtime_config.service_name,
            "dependencies": dependencies,
        }

    @app.get("/healthz")
    def healthz() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "service": active_runtime_config.service_name,
            },
        )

    @app.get("/readyz")
    def readyz() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        ready, payload = current_readiness_payload()
        return JSONResponse(
            status_code=200 if ready else 503,
            content=payload,
        )

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        return PlainTextResponse(
            content=metrics_text(
                {
                    "DATABASE_URL": active_runtime_config.database_url or "",
                    "REDIS_URL": active_runtime_config.redis_url or "",
                    "VECTOR_STORE_URL": active_runtime_config.vector_store_url or "",
                },
                runtime_metrics=chatbi_application.runtime_metrics_snapshot(),
            ),
            media_type="text/plain; version=0.0.4",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        if request.url.path.startswith("/api/v2/"):
            return v2_error_response(
                request_id=v2_request_id_from_header(
                    request.headers.get("x-request-id"),
                    "req_invalid_request",
                ),
                trace_id=new_trace_id_v2(),
                code="VALIDATION_ERROR",
                message="Request payload or parameters are invalid.",
                status_code=400,
            )

        trace_id = request.headers.get("x-trace-id") or new_trace_id()
        envelope = error_envelope(
            code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            message="Request payload or parameters are invalid.",
            trace_id=trace_id,
            data={"details": exc.errors()},
        )
        chatbi_application.record_api_audit(
            trace_id=trace_id,
            user_id="anonymous",
            endpoint=str(request.url.path),
            status_code=400,
            error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
        )
        return response_from_envelope(envelope, status_code=400)

    @app.exception_handler(Exception)
    async def internal_error_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        _exc: Exception,
    ) -> JSONResponse:
        trace_id = request.headers.get("x-trace-id") or new_trace_id()
        if request.url.path.startswith("/api/v2/"):
            return v2_error_response(
                request_id="req_internal_error",
                trace_id=new_trace_id_v2(),
                code="INTERNAL_ERROR",
                message="The API could not complete the request.",
                status_code=500,
            )

        response = error_envelope(
            code=ApiErrorCode.INTERNAL_ERROR,
            message="The API could not complete the request.",
            trace_id=trace_id,
        )
        chatbi_application.record_api_audit(
            trace_id=trace_id,
            user_id="anonymous",
            endpoint=str(request.url.path),
            status_code=500,
            error_code=ApiErrorCode.INTERNAL_ERROR,
        )
        return response_from_envelope(response, status_code=500)

    @app.post("/api/v2/chat/query")
    def chat_query_v2(  # pyright: ignore[reportUnusedFunction]
        body: dict[str, Any],
        authorization: str | None = Header(default=None, alias="Authorization"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        request_id = v2_request_id_from_body(body)
        problems = validate_chat_query_request_v2(body)
        if problems:
            return JSONResponse(
                status_code=400,
                content=validation_error_response_v2(
                    request_id=request_id,
                    trace_id=trace_id,
                    problems=problems,
                ),
            )
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=request_id,
                trace_id=trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        active_request_metadata_store.save_accepted(
            RequestMetadataRecord(
                trace_id=trace_id,
                request_id=request_id,
                session_id=str(body["session_id"]),
                user_id=str(body["user_id"]),
                role=UserRole(str(body["role"])),
                locale=Locale(str(body["locale"])),
                question=str(body["question"]),
            )
        )
        active_observability_logger.record(
            trace_id=trace_id,
            level=LogLevel.INFO,
            message="Accepted v2 chat query.",
            endpoint="/api/v2/chat/query",
            user_id=str(body["user_id"]),
            event="chat_query_accepted",
            request_id=request_id,
            attributes={
                "role": str(body["role"]),
                "locale": str(body["locale"]),
                "session_id": str(body["session_id"]),
            },
        )
        payload = ChatQueryRequestPayload(
            user_id=str(body["user_id"]),
            session_id=str(body["session_id"]),
            question=str(body["question"]),
            locale=Locale(str(body["locale"])),
            role=UserRole(str(body["role"])),
        )
        api_envelope = chatbi_application.handle_chat_query(
            payload,
            trace_id=legacy_trace_id_from_v2(trace_id),
            idempotency_key=idempotency_key,
        )
        if api_envelope.code == 0:
            active_request_metadata_store.mark_succeeded(trace_id)
            if active_runtime_query_result_store is not None:
                runtime_record = runtime_query_result_record_from_response(
                    trace_id=trace_id,
                    session_id=str(body["session_id"]),
                    user_id=str(body["user_id"]),
                    question=str(body["question"]),
                    data=api_envelope.data,
                )
                if runtime_record is not None:
                    active_runtime_query_result_store.save(runtime_record)
            log_level = LogLevel.INFO
            event = "chat_query_succeeded"
        else:
            active_request_metadata_store.mark_failed(trace_id, error_code=str(api_envelope.code))
            log_level = LogLevel.ERROR
            event = "chat_query_failed"
        active_observability_logger.record(
            trace_id=trace_id,
            level=log_level,
            message="Finished v2 chat query.",
            endpoint="/api/v2/chat/query",
            user_id=str(body["user_id"]),
            event=event,
            request_id=request_id,
            attributes={
                "api_code": str(api_envelope.code),
                "warning_count": len(api_envelope.warnings),
            },
        )
        response = v2_response_from_api_envelope(
            api_envelope,
            request_id=request_id,
            trace_id=trace_id,
        )
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=response,
        )

    @app.get("/api/v2/chat/history")
    def chat_history_v2(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        cursor: str | None = None,
        page_size: int = 20,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_history_lookup")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        api_envelope = chatbi_application.handle_chat_history(
            user_id=user_id,
            trace_id=lookup_trace_id,
            cursor=cursor,
            page_size=page_size,
        )
        response = v2_generic_response_from_api_envelope(
            api_envelope,
            request_id=active_request_id,
            trace_id=lookup_trace_id,
        )
        response["data"] = v2_history_data(api_envelope.data)
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=response,
        )

    @app.get("/api/v2/metrics/catalog")
    def metrics_catalog_v2(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_metrics_catalog")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        api_envelope = chatbi_application.handle_metrics_catalog(
            user_id=user_id,
            trace_id=lookup_trace_id,
        )
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=v2_generic_response_from_api_envelope(
                api_envelope,
                request_id=active_request_id,
                trace_id=lookup_trace_id,
            ),
        )

    @app.get("/api/v2/datasets/catalog")
    def datasets_catalog_v2(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_datasets_catalog")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        api_envelope = chatbi_application.handle_datasets_catalog(
            user_id=user_id,
            trace_id=lookup_trace_id,
        )
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=v2_generic_response_from_api_envelope(
                api_envelope,
                request_id=active_request_id,
                trace_id=lookup_trace_id,
            ),
        )

    @app.get("/api/v2/health")
    def health_v2(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_health_check")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        api_envelope = chatbi_application.handle_health_check(
            user_id=user_id,
            trace_id=lookup_trace_id,
        )
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=v2_generic_response_from_api_envelope(
                api_envelope,
                request_id=active_request_id,
                trace_id=lookup_trace_id,
            ),
        )

    @app.get("/api/v2/ready")
    def ready_v2(  # pyright: ignore[reportUnusedFunction]
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_ready_check")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        ready, payload = current_readiness_payload()
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "trace_id": lookup_trace_id,
                "request_id": active_request_id,
                "data": payload,
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/query/{trace_id}")
    def query_detail_v2(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_query_lookup")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        api_envelope = chatbi_application.handle_query_detail(
            trace_id=legacy_trace_id_from_v2(trace_id),
            user_id=user_id,
        )
        if api_envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="QUERY_NOT_FOUND",
                message="Trace id was not found.",
                status_code=404,
            )

        response = v2_generic_response_from_api_envelope(
            api_envelope,
            request_id=active_request_id,
            trace_id=lookup_trace_id,
        )
        response["data"] = v2_query_detail_data(api_envelope.data)
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=response,
        )

    @app.get("/api/v2/requests/{trace_id}")
    def request_metadata_v2(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_lookup_request")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        record = active_request_metadata_store.get(trace_id)
        if record is None:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="REQUEST_NOT_FOUND",
                message="Request metadata was not found for this trace id.",
                status_code=404,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": lookup_trace_id,
                "request_id": active_request_id,
                "data": request_metadata_to_dict(record),
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/chat/tasks/{task_id}")
    def chat_task_status_v2(  # pyright: ignore[reportUnusedFunction]
        task_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_task_lookup")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        record = active_worker_handoff_queue.get(task_id)
        if record is None:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="TASK_NOT_FOUND",
                message="Task id was not found.",
                status_code=404,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": lookup_trace_id,
                "request_id": active_request_id,
                "data": async_task_record_to_dict(record),
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/analytics/analyze")
    def analytics_analyze_v2(  # pyright: ignore[reportUnusedFunction]
        body: AnalyticsRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        active_request_id = v2_request_id_from_header(request_id, "req_analytics_analyze")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=body.trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        try:
            request = body.to_domain()
            result = active_analytics_service.analyze(request)
        except AnalyticsValidationError as exc:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=body.trace_id,
                code=exc.code.value,
                message=str(exc),
                status_code=400,
            )
        except ValueError as exc:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=body.trace_id,
                code="VALIDATION_ERROR",
                message=str(exc),
                status_code=400,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": request.trace_id,
                "request_id": active_request_id,
                "data": {
                    "trace_id": request.trace_id,
                    "metric_id": request.metric_id,
                    "semantic_version_id": request.semantic_version_id,
                    "result": result_to_dict(result),
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/analytics/tasks")
    def analytics_task_v2(  # pyright: ignore[reportUnusedFunction]
        body: AnalyticsRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        active_request_id = v2_request_id_from_header(request_id, "req_analytics_task")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=body.trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        try:
            request = body.to_domain()
        except ValueError as exc:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=body.trace_id,
                code="VALIDATION_ERROR",
                message=str(exc),
                status_code=400,
            )

        task = active_worker_handoff_queue.enqueue(
            AsyncTaskRequest(
                trace_id=request.trace_id,
                kind=AsyncTaskKind.ANALYTICS,
                payload={"request": body.to_task_payload()},
            )
        )
        return JSONResponse(
            status_code=202,
            content={
                "trace_id": request.trace_id,
                "request_id": active_request_id,
                "data": async_task_record_to_dict(task),
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/analytics/results/{trace_id}")
    def analytics_result_v2(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        active_request_id = v2_request_id_from_header(request_id, "req_analytics_result")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        record = active_analytics_service.result_by_trace_id(trace_id)
        if record is None:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="ANALYTICS_RESULT_NOT_FOUND",
                message="Analytics result was not found for trace id.",
                status_code=404,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "trace_id": record.trace_id,
                    "metric_id": record.metric_id,
                    "semantic_version_id": record.semantic_version_id,
                    "parameters": dict(record.parameters),
                    "result": result_to_dict(record.result),
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/documents/index")
    def document_index_v2(  # pyright: ignore[reportUnusedFunction]
        body: DocumentIndexRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        active_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_document_index")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=active_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        validation_errors = body.validation_errors()
        if validation_errors:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=active_trace_id,
                code="VALIDATION_ERROR",
                message="Document index request is invalid.",
                status_code=400,
            )

        body_fingerprint = body.idempotency_fingerprint()
        if idempotency_key is not None:
            cache_key = ("v2_documents_index", idempotency_key)
            cached = document_index_idempotency_cache.get(cache_key)
            if cached is not None:
                if cached.body_fingerprint != body_fingerprint:
                    return v2_error_response(
                        request_id=active_request_id,
                        trace_id=active_trace_id,
                        code="VALIDATION_ERROR",
                        message=(
                            "Idempotency-Key was reused with a different document index request."
                        ),
                        status_code=400,
                    )
                return JSONResponse(
                    status_code=202,
                    content={
                        "trace_id": active_trace_id,
                        "request_id": active_request_id,
                        "data": document_index_response_data(body, cached.task),
                        "warnings": [],
                        "error": None,
                    },
                )

        task = active_worker_handoff_queue.enqueue(
            AsyncTaskRequest(
                trace_id=active_trace_id,
                kind=AsyncTaskKind.INDEXING,
                payload=body.to_task_payload(),
            )
        )
        if idempotency_key is not None:
            document_index_idempotency_cache[("v2_documents_index", idempotency_key)] = (
                DocumentIndexIdempotencyEntry(
                    body_fingerprint=body_fingerprint,
                    task=task,
                )
            )

        return JSONResponse(
            status_code=202,
            content={
                "trace_id": active_trace_id,
                "request_id": active_request_id,
                "data": document_index_response_data(body, task),
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/query-results/{trace_id}")
    def query_result_v2(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_query_result_lookup")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        record = (
            active_runtime_query_result_store.get(trace_id)
            if active_runtime_query_result_store is not None
            else None
        )
        if record is None:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="QUERY_RESULT_NOT_FOUND",
                message="Runtime query result was not found for this trace id.",
                status_code=404,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": lookup_trace_id,
                "request_id": active_request_id,
                "data": runtime_query_result_to_dict(record),
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/governance/traces/{trace_id}")
    def governance_trace_v2(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        lookup_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_governance_trace_lookup")
        if authorization is None or not authorization.startswith("Bearer "):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )

        request_record = active_request_metadata_store.get(trace_id)
        query_result_record = (
            active_runtime_query_result_store.get(trace_id)
            if active_runtime_query_result_store is not None
            else None
        )
        guardrail_record = (
            active_guardrail_audit_log_v2.get_v2(trace_id)
            if active_guardrail_audit_log_v2 is not None
            else None
        )
        if request_record is None and query_result_record is None and guardrail_record is None:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=lookup_trace_id,
                code="GOVERNANCE_TRACE_NOT_FOUND",
                message="Governance trace evidence was not found for this trace id.",
                status_code=404,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": lookup_trace_id,
                "request_id": active_request_id,
                "data": governance_trace_summary(
                    trace_id=trace_id,
                    request_record=request_record,
                    query_result_record=query_result_record,
                    guardrail_record=guardrail_record,
                ),
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v1/chat/query")
    def chat_query(  # pyright: ignore[reportUnusedFunction]
        body: ChatQueryRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/chat/query",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_chat_query(
            body.to_payload(),
            trace_id=active_trace_id,
            idempotency_key=idempotency_key,
        )
        if envelope.code == 0 and active_runtime_query_result_store is not None:
            runtime_record = runtime_query_result_record_from_response(
                trace_id=active_trace_id,
                session_id=body.session_id,
                user_id=body.user_id,
                question=body.question,
                data=envelope.data,
            )
            if runtime_record is not None:
                active_runtime_query_result_store.save(runtime_record)
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/chat/tasks/{task_id}")
    def chat_task_status(  # pyright: ignore[reportUnusedFunction]
        task_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            f"/api/v1/chat/tasks/{task_id}",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        record = active_worker_handoff_queue.get(task_id)
        if record is None:
            response = error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message="Task id was not found.",
                trace_id=active_trace_id,
            )
            chatbi_application.record_api_audit(
                trace_id=active_trace_id,
                user_id=user_id,
                endpoint=f"/api/v1/chat/tasks/{task_id}",
                status_code=404,
                error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            )
            return response_from_envelope(response, status_code=404)

        response = envelope(
            data=async_task_record_to_dict(record),
            trace_id=active_trace_id,
        )
        chatbi_application.record_api_audit(
            trace_id=active_trace_id,
            user_id=user_id,
            endpoint=f"/api/v1/chat/tasks/{task_id}",
            status_code=200,
        )
        return response_from_envelope(response)

    @app.post("/api/v1/documents/index")
    def document_index(  # pyright: ignore[reportUnusedFunction]
        body: DocumentIndexRequestBody,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/documents/index",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        validation_errors = body.validation_errors()
        if validation_errors:
            response = error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message="Document index request is invalid.",
                trace_id=active_trace_id,
                data={"errors": validation_errors},
            )
            chatbi_application.record_api_audit(
                trace_id=active_trace_id,
                user_id=user_id,
                endpoint="/api/v1/documents/index",
                status_code=400,
                error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            )
            return response_from_envelope(response, status_code=400)

        body_fingerprint = body.idempotency_fingerprint()
        if idempotency_key is not None:
            cache_key = ("v1_documents_index", user_id, idempotency_key)
            cached = document_index_idempotency_cache.get(cache_key)
            if cached is not None:
                if cached.body_fingerprint != body_fingerprint:
                    response = error_envelope(
                        code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                        message=(
                            "Idempotency-Key was reused with a different document index request."
                        ),
                        trace_id=active_trace_id,
                    )
                    chatbi_application.record_api_audit(
                        trace_id=active_trace_id,
                        user_id=user_id,
                        endpoint="/api/v1/documents/index",
                        status_code=400,
                        error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                    )
                    return response_from_envelope(response, status_code=400)

                response = envelope(
                    data=document_index_response_data(body, cached.task),
                    trace_id=active_trace_id,
                )
                chatbi_application.record_api_audit(
                    trace_id=active_trace_id,
                    user_id=user_id,
                    endpoint="/api/v1/documents/index",
                    status_code=202,
                )
                return response_from_envelope(response, status_code=202)

        task = active_worker_handoff_queue.enqueue(
            AsyncTaskRequest(
                trace_id=active_trace_id,
                kind=AsyncTaskKind.INDEXING,
                payload=body.to_task_payload(),
            )
        )
        if idempotency_key is not None:
            document_index_idempotency_cache[("v1_documents_index", user_id, idempotency_key)] = (
                DocumentIndexIdempotencyEntry(
                    body_fingerprint=body_fingerprint,
                    task=task,
                )
            )
        response = envelope(
            data=document_index_response_data(body, task),
            trace_id=active_trace_id,
        )
        chatbi_application.record_api_audit(
            trace_id=active_trace_id,
            user_id=user_id,
            endpoint="/api/v1/documents/index",
            status_code=202,
        )
        return response_from_envelope(response, status_code=202)

    @app.post("/api/v1/sql/preview")
    def sql_preview(  # pyright: ignore[reportUnusedFunction]
        body: SqlPreviewRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/sql/preview",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        result = SemanticNl2SqlPipeline().run(
            request=body.to_query_request(),
            trace_id=active_trace_id,
        )
        if result.sql_preview is not None:
            guardrail_decision = SimpleSqlGuardrailV2(
                audit_log=active_guardrail_audit_log_v2,
            ).check(
                GuardrailRequestV2(
                    trace_id=active_trace_id,
                    user_id=body.user_id,
                    role=body.role.value,
                    sql_text=result.sql_preview.sql_text,
                    semantic_version_id=result.sql_preview.semantic_version_id,
                )
            )
            response_data = {
                **asdict(result.sql_preview),
                "guardrail_decision": _guardrail_decision_to_dict(guardrail_decision),
            }
            response = envelope(
                data=response_data,
                trace_id=active_trace_id,
            )
            chatbi_application.record_api_audit(
                trace_id=active_trace_id,
                user_id=body.user_id,
                endpoint="/api/v1/sql/preview",
                status_code=200,
            )
            return response_from_envelope(response)

        response_code = ApiErrorCode.REQ_INVALID_ARGUMENT
        status_code = 400
        message = result.clarification or "SQL preview could not be generated."
        if result.semantic_resolution.status is SemanticResolveStatus.PERMISSION_DENIED:
            response_code = ApiErrorCode.AUTH_FORBIDDEN
            status_code = 403
            if result.guardrail_result is not None and result.guardrail_result.message is not None:
                message = result.guardrail_result.message

        response = error_envelope(
            code=response_code,
            message=message,
            trace_id=active_trace_id,
            data={
                "semantic_resolution": _semantic_resolution_to_dict(result.semantic_resolution),
                "sql_preview": None,
            },
        )
        chatbi_application.record_api_audit(
            trace_id=active_trace_id,
            user_id=body.user_id,
            endpoint="/api/v1/sql/preview",
            status_code=status_code,
            error_code=response_code,
        )
        return response_from_envelope(response, status_code=status_code)

    @app.post("/api/v1/sql/guardrail/check")
    def sql_guardrail_check(  # pyright: ignore[reportUnusedFunction]
        body: SqlGuardrailCheckRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/sql/guardrail/check",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        guardrail_decision = SimpleSqlGuardrailV2(
            audit_log=active_guardrail_audit_log_v2,
        ).check(body.to_guardrail_request(active_trace_id))
        response = envelope(
            data=_guardrail_decision_to_dict(guardrail_decision),
            trace_id=active_trace_id,
        )
        chatbi_application.record_api_audit(
            trace_id=active_trace_id,
            user_id=body.user_id,
            endpoint="/api/v1/sql/guardrail/check",
            status_code=200,
        )
        return response_from_envelope(response)

    @app.get("/api/v1/chat/history")
    def chat_history(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        cursor: str | None = None,
        page_size: int = 20,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/chat/history",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_chat_history(
            user_id=user_id,
            trace_id=active_trace_id,
            cursor=cursor,
            page_size=page_size,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/query/{trace_id}")
    def query_detail(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        _, rejected = require_headers(
            chatbi_application,
            f"/api/v1/query/{trace_id}",
            request_trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_query_detail(trace_id=trace_id, user_id=user_id)
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/metrics/catalog")
    def metrics_catalog(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/metrics/catalog",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_metrics_catalog(
            user_id=user_id,
            trace_id=active_trace_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/datasets/catalog")
    def datasets_catalog(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/datasets/catalog",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_datasets_catalog(
            user_id=user_id,
            trace_id=active_trace_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/audit/{trace_id}")
    def audit_detail(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        _, rejected = require_headers(
            chatbi_application,
            f"/api/v1/audit/{trace_id}",
            request_trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_audit_detail(trace_id=trace_id, user_id=user_id)
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/observability/traces/{trace_id}")
    def observability_trace_detail(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        _, rejected = require_headers(
            chatbi_application,
            f"/api/v1/observability/traces/{trace_id}",
            request_trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_observability_trace_detail(
            trace_id=trace_id,
            user_id=user_id,
        )
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/quality/dashboard")
    def quality_dashboard(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/quality/dashboard",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_quality_dashboard(
            user_id=user_id,
            trace_id=active_trace_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.post("/api/v1/evals/run")
    def eval_run(  # pyright: ignore[reportUnusedFunction]
        body: EvalRunRequestBody,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/evals/run",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_eval_run(
            user_id=user_id,
            trace_id=active_trace_id,
            payload=body.to_payload(),
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/evals/{eval_run_id}")
    def eval_report(  # pyright: ignore[reportUnusedFunction]
        eval_run_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            f"/api/v1/evals/{eval_run_id}",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_eval_report(
            user_id=user_id,
            trace_id=active_trace_id,
            eval_run_id=eval_run_id,
        )
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/health")
    def health(  # pyright: ignore[reportUnusedFunction]
        user_id: str = "system",
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/health",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_health_check(
            user_id=user_id,
            trace_id=active_trace_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    return app


app = create_app(
    use_postgres_metadata=use_postgres_metadata_from_env(),
    database_readiness_checker=database_readiness_checker_from_env(),
    redis_readiness_checker=redis_readiness_checker_from_env(),
    readonly_database_probe=readonly_database_probe_from_env(),
)
