"""FastAPI entry point for the Backend API slice."""

from __future__ import annotations

from hashlib import sha256
import os
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
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
from chatbi.auth import (
    AuthContext,
    AuthService,
    InMemoryAuthStore,
    InvalidCredentials,
    PasswordHasher,
    PermissionDenied,
    SignUpRequest,
    TokenExpired,
    TokenService,
    dev_test_auth_context,
    postgres_auth_store_from_psycopg,
    require_permission,
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
from chatbi.embedding_vector_config import build_embedding_vector_rag_service_from_runtime_config
from chatbi.embedding_vector_rag import DocumentRecord, EmbeddingVectorRagService
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
from chatbi.governance.query_audit import QueryAuditLog, QueryAuditRecord
from chatbi.llm import build_llm_client_from_runtime_config
from chatbi.knowledge import (
    ChunkEmbedding,
    DocumentChunk,
    InMemoryKnowledgeStore,
    KnowledgeDocument,
    text_embedding,
)
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


class SignUpRequestBody(BaseModel):
    email: str
    password: str
    display_name: str
    organization_name: str | None = None

    def to_auth_request(self) -> SignUpRequest:
        return SignUpRequest(
            email=self.email,
            password=self.password,
            display_name=self.display_name,
            organization_name=self.organization_name,
        )


class SignInRequestBody(BaseModel):
    email: str
    password: str


class RefreshTokenRequestBody(BaseModel):
    refresh_token: str


class RoleUpdateRequestBody(BaseModel):
    roles: tuple[str, ...]


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

    def to_domain(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> AnalyticsRequest:
        return AnalyticsRequest(
            trace_id=self.trace_id,
            metric_id=self.metric_id,
            semantic_version_id=self.semantic_version_id,
            time_column=self.time_column,
            value_column=self.value_column,
            grain=self.grain,
            rows=self.rows,
            analysis_options=self.analysis_options.to_domain(),
            org_id=org_id,
            user_id=user_id,
        )

    def to_task_payload(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> Mapping[str, object]:
        payload: dict[str, object] = {
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
        if org_id is not None:
            payload["org_id"] = org_id
        if user_id is not None:
            payload["user_id"] = user_id
        return payload


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

    def to_task_payload(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> Mapping[str, object]:
        payload: dict[str, object] = {
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
        if org_id is not None:
            payload["org_id"] = org_id
        if user_id is not None:
            payload["user_id"] = user_id
        return payload

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
    if envelope.code is ApiErrorCode.SQL_GUARDRAIL_BLOCKED:
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


def _load_knowledge_store_from_db(
    connect_fn: Callable[[str], Any],
    database_url: str,
) -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    try:
        conn = connect_fn(database_url)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, title, doc_type, publish_time, business_tags, allowed_roles"
                " FROM knowledge.documents"
            )
            for row in cur.fetchall():
                source_id, title, doc_type, publish_time, business_tags, allowed_roles = row
                store.save_document(
                    KnowledgeDocument(
                        source_id=source_id,
                        title=title,
                        doc_type=doc_type,
                        publish_time=publish_time,
                        tags=tuple(business_tags or []),
                        allowed_roles=tuple(allowed_roles or []),
                    )
                )
            cur.execute(
                "SELECT chunk_id, source_id, chunk_index, chunk_text"
                " FROM knowledge.doc_chunks ORDER BY source_id, chunk_index"
            )
            for row in cur.fetchall():
                chunk_id, source_id, chunk_index, chunk_text = row
                if source_id not in store._documents_by_source_id:
                    continue
                store.save_chunk(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        source_id=source_id,
                        chunk_index=chunk_index,
                        chunk_text=chunk_text,
                    )
                )
                store.save_embedding(
                    ChunkEmbedding(
                        embedding_id=f"{chunk_id}_emb",
                        chunk_id=chunk_id,
                        embedding_vector=text_embedding(chunk_text),
                    )
                )
    except Exception:
        pass  # DB not ready yet; fall back to empty store
    return store


def _build_default_chatbi_application(
    runtime_config: RuntimeConfig,
    readonly_query_connect: Callable[[str], Any] | None = None,
) -> ChatBIApplication:
    llm_client = build_llm_client_from_runtime_config(runtime_config)
    knowledge_store = (
        _load_knowledge_store_from_db(connect_psycopg, runtime_config.database_url)
        if runtime_config.database_url
        else InMemoryKnowledgeStore()
    )
    if runtime_config.readonly_database_url is None:
        return ChatBIApplication(
            orchestrator=SimpleOrchestrator(
                llm_client=llm_client,
                knowledge_store=knowledge_store,
            )
        )

    return ChatBIApplication(
        orchestrator=SimpleOrchestrator(
            llm_client=llm_client,
            knowledge_store=knowledge_store,
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


def _build_default_auth_service(
    runtime_config: RuntimeConfig | None = None,
    connect: Callable[[str], Any] | None = None,
    use_postgres_metadata: bool = False,
    env: Mapping[str, str] | None = None,
) -> AuthService:
    runtime_env = env or os.environ
    secret = runtime_env.get("CHATBI_AUTH_TOKEN_SECRET") or f"runtime_{uuid4().hex}"
    store: InMemoryAuthStore | Any = InMemoryAuthStore()
    if (
        use_postgres_metadata
        and runtime_config is not None
        and runtime_config.database_url is not None
    ):
        store = postgres_auth_store_from_psycopg(
            (connect or connect_psycopg)(runtime_config.database_url)
        )
        store.initialize_schema()
    return AuthService(
        store=store,
        password_hasher=PasswordHasher(),
        token_service=TokenService(secret=secret),
    )


def auth_response_data(user: object, tokens: object) -> dict[str, object]:
    return {
        "user": {
            "user_id": getattr(user, "user_id"),
            "email": getattr(user, "email"),
            "display_name": getattr(user, "display_name"),
            "org_id": getattr(user, "org_id"),
            "roles": list(getattr(user, "roles")),
            "permissions": list(getattr(user, "permissions")),
        },
        "tokens": {
            "access_token": getattr(tokens, "access_token"),
            "refresh_token": getattr(tokens, "refresh_token"),
            "expires_in": getattr(tokens, "expires_in"),
            "token_type": getattr(tokens, "token_type"),
        },
    }


def role_audit_event_to_dict(event: object) -> dict[str, object]:
    return {
        "audit_event_id": getattr(event, "audit_event_id"),
        "org_id": getattr(event, "org_id"),
        "actor_user_id": getattr(event, "actor_user_id"),
        "target_user_id": getattr(event, "target_user_id"),
        "action": getattr(event, "action"),
        "roles_before": list(getattr(event, "roles_before")),
        "roles_after": list(getattr(event, "roles_after")),
        "permissions_before": list(getattr(event, "permissions_before")),
        "permissions_after": list(getattr(event, "permissions_after")),
        "occurred_at": _isoformat_or_none(getattr(event, "occurred_at", None)),
    }


def request_metadata_to_dict(record: RequestMetadataRecord) -> dict[str, Any]:
    return {
        "trace_id": record.trace_id,
        "request_id": record.request_id,
        "org_id": getattr(record, "org_id", None),
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
    org_id: str | None = None,
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
        org_id=org_id,
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
        "org_id": record.org_id,
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


def index_document_into_vector_rag(
    *,
    service: EmbeddingVectorRagService | None,
    body: DocumentIndexRequestBody,
    trace_id: str,
    org_id: str,
    user_id: str,
) -> Mapping[str, object] | None:
    if service is None:
        return None
    chunks = service.index_document(
        trace_id=trace_id,
        document=DocumentRecord(
            document_id=body.document_id,
            org_id=org_id,
            title=body.title,
            source_type=body.document_type,
            owner_user_id=user_id,
            version=_document_version_from_published_at(body.published_at),
            access_policy={"permission_tags": body.permission_tags},
        ),
        text=body.text,
    )
    return {
        "vector_indexed": True,
        "indexed_chunk_count": len(chunks),
        "embedding_model": service.embedding_model_name,
    }


def _document_version_from_published_at(published_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return published_at
    return parsed.date().isoformat()


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


def admin_observability_summary_payload(
    *,
    runtime_config: RuntimeConfig,
    readiness_payload: Mapping[str, object],
    application: ChatBIApplication,
    request_metadata_store: RequestMetadataStore,
    runtime_query_result_store: RuntimeQueryResultStore | None,
    guardrail_audit_log: GuardrailAuditLogV2 | None,
    embedding_vector_rag_service: EmbeddingVectorRagService | None,
    org_id: str,
    user_id: str,
) -> dict[str, object]:
    latest_eval_run = _latest_eval_run(application, org_id)
    release_gate = _release_gate_summary(latest_eval_run)
    request_records = _request_metadata_for_org(request_metadata_store, org_id)
    runtime_result_records = _runtime_query_results_for_org(runtime_query_result_store, org_id)
    guardrail_records = _guardrail_audit_records(guardrail_audit_log)
    org_guardrail_records = tuple(
        record
        for record in guardrail_records
        if _trace_in_request_records(str(getattr(record, "trace_id", "")), request_records)
    )

    return {
        "system_health": {
            "status": readiness_payload.get("status", "unknown"),
            "service": readiness_payload.get("service", runtime_config.service_name),
            "dependencies": readiness_payload.get("dependencies", {}),
            "request_count": len(request_records),
        },
        "llm_health": {
            "provider": runtime_config.llm_provider,
            "model": runtime_config.llm_model,
            "configured": runtime_config.llm_provider_configured,
            "mock": runtime_config.llm_provider == "mock",
        },
        "sql_safety": {
            "guardrail_audit_count": len(org_guardrail_records),
            "denied_count": _guardrail_decision_count(org_guardrail_records, "deny"),
            "allowed_count": _guardrail_decision_count(org_guardrail_records, "allow"),
            "runtime_query_result_count": len(runtime_result_records),
        },
        "rag_health": {
            "embedding_provider": runtime_config.embedding_provider,
            "embedding_model": runtime_config.embedding_model,
            "vector_store_configured": runtime_config.vector_store_url is not None,
            "vector_rag_active": embedding_vector_rag_service is not None,
        },
        "eval_summary": _eval_summary(latest_eval_run),
        "release_gate": release_gate,
        "audit_summary": {
            "api_audit_count": len(_api_audit_records_for_user(application, user_id)),
            "admin_observability_read_count": len(
                tuple(
                    record
                    for record in _api_audit_records_for_user(application, user_id)
                    if getattr(record, "endpoint", "")
                    == "/api/v2/admin/observability/summary"
                )
            ),
            "guardrail_audit_count": len(org_guardrail_records),
        },
    }


def _api_audit_records_for_user(
    application: ChatBIApplication,
    user_id: str,
) -> tuple[object, ...]:
    return tuple(
        record
        for record in application.audit_records
        if getattr(record, "user_id", None) == user_id
    )


def _latest_eval_run(application: ChatBIApplication, org_id: str) -> object | None:
    latest_run = getattr(application.evaluation_repository, "latest_run", None)
    if callable(latest_run):
        return latest_run(org_id)
    return None


def _eval_summary(latest_eval_run: object | None) -> dict[str, object]:
    if latest_eval_run is None:
        return {
            "latest_eval_run_id": None,
            "status": "not_run",
            "total_cases": 0,
            "passed_cases": 0,
            "failed_cases": 0,
            "sql_safety_score": None,
        }
    return {
        "latest_eval_run_id": getattr(latest_eval_run, "eval_run_id", None),
        "eval_suite_id": getattr(latest_eval_run, "eval_suite_id", None),
        "status": getattr(getattr(latest_eval_run, "status", None), "value", None),
        "total_cases": getattr(latest_eval_run, "total_cases", 0),
        "passed_cases": getattr(latest_eval_run, "passed_cases", 0),
        "failed_cases": getattr(latest_eval_run, "failed_cases", 0),
        "sql_safety_score": getattr(latest_eval_run, "sql_safety_score", None),
    }


def _release_gate_summary(latest_eval_run: object | None) -> dict[str, object]:
    if latest_eval_run is None:
        return {
            "release_gate_passed": None,
            "blocking": False,
            "blocking_reason": None,
            "failed_cases": 0,
        }
    failed_cases = int(getattr(latest_eval_run, "failed_cases", 0))
    release_gate_passed = bool(getattr(latest_eval_run, "release_gate_passed", False))
    eval_run_id = getattr(latest_eval_run, "eval_run_id", None)
    return {
        "eval_run_id": eval_run_id,
        "release_gate_passed": release_gate_passed,
        "blocking": not release_gate_passed,
        "blocking_reason": (
            None
            if release_gate_passed
            else _release_gate_blocking_reason(latest_eval_run)
        ),
        "failed_cases": failed_cases,
        "eval_report_path": f"/api/v2/evals/{eval_run_id}" if isinstance(eval_run_id, str) else None,
    }


def _release_gate_blocking_reason(latest_eval_run: object) -> str:
    failed_cases = int(getattr(latest_eval_run, "failed_cases", 0))
    sql_safety_score = getattr(latest_eval_run, "sql_safety_score", None)
    if isinstance(sql_safety_score, float) and sql_safety_score < 1.0:
        return f"Release blocked because SQL safety score was {sql_safety_score}."
    if failed_cases:
        return f"Release blocked because latest eval run failed {failed_cases} case(s)."
    return "Release blocked because latest eval run did not pass the release gate."


def _request_metadata_for_org(
    request_metadata_store: RequestMetadataStore,
    org_id: str,
) -> tuple[RequestMetadataRecord, ...]:
    list_all = getattr(request_metadata_store, "list_all", None)
    if not callable(list_all):
        return ()
    return tuple(
        record
        for record in cast(Sequence[RequestMetadataRecord], list_all())
        if record.org_id == org_id
    )


def _runtime_query_results_for_org(
    runtime_query_result_store: RuntimeQueryResultStore | None,
    org_id: str,
) -> tuple[object, ...]:
    if runtime_query_result_store is None:
        return ()
    records = getattr(runtime_query_result_store, "_records", None)
    if not isinstance(records, dict):
        return ()
    return tuple(
        record
        for record in cast(Mapping[str, object], records).values()
        if getattr(record, "org_id", None) == org_id
    )


def _guardrail_audit_records(guardrail_audit_log: GuardrailAuditLogV2 | None) -> tuple[object, ...]:
    if guardrail_audit_log is None:
        return ()
    list_all = getattr(guardrail_audit_log, "list_all_v2", None)
    if not callable(list_all):
        return ()
    return tuple(cast(Sequence[object], list_all()))


def _trace_in_request_records(trace_id: str, records: tuple[RequestMetadataRecord, ...]) -> bool:
    return any(record.trace_id == trace_id for record in records)


def _guardrail_decision_count(records: tuple[object, ...], decision_value: str) -> int:
    return sum(
        1
        for record in records
        if getattr(getattr(record, "decision", None), "value", None) == decision_value
    )


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
        "agent_timeline": [
            _json_safe_mapping(cast(Mapping[str, Any], item))
            for item in _v2_iterable(data.get("agent_timeline"))
            if isinstance(item, Mapping)
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
    auth_connect: Callable[[str], Any] | None = None,
    readonly_query_connect: Callable[[str], Any] | None = None,
    use_postgres_metadata: bool = False,
    database_readiness_checker: DatabaseReadinessChecker | None = None,
    redis_readiness_checker: RedisReadinessChecker | None = None,
    readonly_database_probe: ReadOnlyDatabaseProbeRunner | None = None,
    observability_logger: ObservabilityLogger | None = None,
    guardrail_audit_log_v2: GuardrailAuditLogV2 | None = None,
    worker_handoff_queue: WorkerHandoffQueue | None = None,
    analytics_service: AnalyticsService | None = None,
    auth_service: AuthService | None = None,
    embedding_vector_rag_service: EmbeddingVectorRagService | None = None,
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
    active_embedding_vector_rag_service = (
        embedding_vector_rag_service
        if embedding_vector_rag_service is not None
        else build_embedding_vector_rag_service_from_runtime_config(active_runtime_config)
    )
    active_auth_service = auth_service or _build_default_auth_service(
        runtime_config=active_runtime_config,
        connect=auth_connect,
        use_postgres_metadata=use_postgres_metadata,
    )
    active_query_audit_log: QueryAuditLog | None = None
    if active_runtime_config.database_url:
        try:
            _audit_conn = connect_psycopg(active_runtime_config.database_url)
            active_query_audit_log = QueryAuditLog(_audit_conn)
            active_query_audit_log.initialize_schema()
        except Exception:
            active_query_audit_log = None
    document_index_idempotency_cache: dict[
        tuple[str, ...],
        DocumentIndexIdempotencyEntry,
    ] = {}
    app = FastAPI(title="Governed ChatBI Platform", version="0.1.0")

    def authenticate_v2(
        authorization: str | None,
        trace_id: str,
        request_id: str,
        *,
        required_permission: str | None = None,
    ) -> tuple[AuthContext | None, JSONResponse | None]:
        if authorization is None or not authorization.startswith("Bearer "):
            return None, v2_error_response(
                request_id=request_id,
                trace_id=trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Missing or invalid bearer token.",
                status_code=401,
            )
        token = authorization.removeprefix("Bearer ").strip()
        if token == "test-token":
            context = dev_test_auth_context(trace_id)
        else:
            try:
                context = active_auth_service.authenticate_access_token(token, trace_id=trace_id)
            except TokenExpired:
                return None, v2_error_response(
                    request_id=request_id,
                    trace_id=trace_id,
                    code="AUTH_UNAUTHORIZED",
                    message="Access token is expired.",
                    status_code=401,
                )
            except InvalidCredentials:
                return None, v2_error_response(
                    request_id=request_id,
                    trace_id=trace_id,
                    code="AUTH_UNAUTHORIZED",
                    message="Missing or invalid bearer token.",
                    status_code=401,
                )
        if required_permission is not None:
            try:
                require_permission(context, required_permission)
            except PermissionDenied:
                return None, v2_error_response(
                    request_id=request_id,
                    trace_id=trace_id,
                    code="AUTH_FORBIDDEN",
                    message="The authenticated user is not allowed to access this resource.",
                    status_code=403,
                )
        return context, None

    def require_v2_permissions(
        auth_context: AuthContext,
        trace_id: str,
        request_id: str,
        permissions: tuple[str, ...],
    ) -> JSONResponse | None:
        for permission in permissions:
            try:
                require_permission(auth_context, permission)
            except PermissionDenied:
                return v2_error_response(
                    request_id=request_id,
                    trace_id=trace_id,
                    code="AUTH_FORBIDDEN",
                    message="The authenticated user is not allowed to access this resource.",
                    status_code=403,
                )
        return None

    def authenticate_v1(
        endpoint: str,
        trace_id: str | None,
        authorization: str | None,
        *,
        required_permission: str | None = None,
    ) -> tuple[AuthContext | None, str, JSONResponse | None]:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            endpoint,
            trace_id,
            authorization,
        )
        if rejected is not None:
            return None, active_trace_id, rejected

        token = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if token == "test-token":
            context = dev_test_auth_context(active_trace_id)
        else:
            try:
                context = active_auth_service.authenticate_access_token(
                    token,
                    trace_id=active_trace_id,
                )
            except TokenExpired:
                response = error_envelope(
                    code=ApiErrorCode.AUTH_UNAUTHORIZED,
                    message="Access token is expired.",
                    trace_id=active_trace_id,
                )
                chatbi_application.record_api_audit(
                    trace_id=active_trace_id,
                    user_id="anonymous",
                    endpoint=endpoint,
                    status_code=401,
                    error_code=ApiErrorCode.AUTH_UNAUTHORIZED,
                )
                return None, active_trace_id, response_from_envelope(
                    response,
                    status_code=401,
                )
            except InvalidCredentials:
                response = error_envelope(
                    code=ApiErrorCode.AUTH_UNAUTHORIZED,
                    message="Missing or invalid bearer token.",
                    trace_id=active_trace_id,
                )
                chatbi_application.record_api_audit(
                    trace_id=active_trace_id,
                    user_id="anonymous",
                    endpoint=endpoint,
                    status_code=401,
                    error_code=ApiErrorCode.AUTH_UNAUTHORIZED,
                )
                return None, active_trace_id, response_from_envelope(
                    response,
                    status_code=401,
                )

        if required_permission is not None:
            try:
                require_permission(context, required_permission)
            except PermissionDenied:
                response = error_envelope(
                    code=ApiErrorCode.AUTH_FORBIDDEN,
                    message="The authenticated user is not allowed to access this resource.",
                    trace_id=active_trace_id,
                )
                chatbi_application.record_api_audit(
                    trace_id=active_trace_id,
                    user_id=context.user_id,
                    endpoint=endpoint,
                    status_code=403,
                    error_code=ApiErrorCode.AUTH_FORBIDDEN,
                )
                return context, active_trace_id, response_from_envelope(
                    response,
                    status_code=403,
                )

        return context, active_trace_id, None

    def tenant_not_found_response(
        request_id: str,
        trace_id: str,
        code: str,
        message: str,
    ) -> JSONResponse:
        return v2_error_response(
            request_id=request_id,
            trace_id=trace_id,
            code=code,
            message=message,
            status_code=404,
        )

    def task_visible_to_context(record: AsyncTaskRecord, auth_context: AuthContext) -> bool:
        org_id = record.payload.get("org_id")
        user_id = record.payload.get("user_id")
        if org_id is not None and org_id != auth_context.org_id:
            return False
        if user_id is not None and user_id != auth_context.user_id:
            return False
        return True

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

    @app.post("/api/v2/auth/signup")
    def auth_signup_v2(  # pyright: ignore[reportUnusedFunction]
        body: SignUpRequestBody,
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_auth_signup")
        try:
            user, tokens = active_auth_service.sign_up(body.to_auth_request())
        except ValueError as exc:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message=str(exc),
                status_code=400,
            )
        return JSONResponse(
            status_code=201,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": auth_response_data(user, tokens),
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/auth/signin")
    def auth_signin_v2(  # pyright: ignore[reportUnusedFunction]
        body: SignInRequestBody,
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_auth_signin")
        try:
            user, tokens = active_auth_service.sign_in(body.email, body.password)
        except InvalidCredentials:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Email or password is invalid.",
                status_code=401,
            )
        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": auth_response_data(user, tokens),
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/auth/refresh")
    def auth_refresh_v2(  # pyright: ignore[reportUnusedFunction]
        body: RefreshTokenRequestBody,
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_auth_refresh")
        try:
            user, tokens = active_auth_service.refresh(body.refresh_token)
        except InvalidCredentials:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_UNAUTHORIZED",
                message="Refresh token is invalid.",
                status_code=401,
            )
        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": auth_response_data(user, tokens),
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/auth/sessions/revoke")
    def auth_revoke_session_v2(  # pyright: ignore[reportUnusedFunction]
        body: RefreshTokenRequestBody,
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_auth_revoke")
        active_auth_service.revoke_refresh_token(body.refresh_token)
        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {"revoked": True},
                "warnings": [],
                "error": None,
            },
        )

    @app.put("/api/v2/admin/users/{target_user_id}/roles")
    def admin_update_roles_v2(  # pyright: ignore[reportUnusedFunction]
        target_user_id: str,
        body: RoleUpdateRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_admin_user_roles")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="admin:user:write",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)
        try:
            user = active_auth_service.update_user_roles(
                actor=auth_context,
                target_user_id=target_user_id,
                roles=body.roles,
            )
        except KeyError:
            return tenant_not_found_response(
                active_request_id,
                trace_id,
                "USER_NOT_FOUND",
                "User was not found.",
            )
        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "user_id": user.user_id,
                    "org_id": user.org_id,
                    "roles": list(user.roles),
                    "permissions": list(user.permissions),
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/admin/audits/roles")
    def admin_role_audits_v2(  # pyright: ignore[reportUnusedFunction]
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_admin_role_audits")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="admin:audit:read",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)
        events = active_auth_service.list_role_audit_events(auth_context)
        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "items": [role_audit_event_to_dict(event) for event in events],
                    "count": len(events),
                },
                "warnings": [],
                "error": None,
            },
        )

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
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            request_id,
            required_permission="chat:query",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)
        effective_user_id = (
            str(body["user_id"])
            if authorization == "Bearer test-token"
            else auth_context.user_id
        )
        effective_role = (
            str(body["role"])
            if authorization == "Bearer test-token"
            else (auth_context.roles[0] if auth_context.roles else str(body["role"]))
        )

        active_request_metadata_store.save_accepted(
            RequestMetadataRecord(
                trace_id=trace_id,
                request_id=request_id,
                session_id=str(body["session_id"]),
                user_id=effective_user_id,
                role=UserRole(effective_role),
                locale=Locale(str(body["locale"])),
                question=str(body["question"]),
                org_id=auth_context.org_id,
            )
        )
        active_observability_logger.record(
            trace_id=trace_id,
            level=LogLevel.INFO,
            message="Accepted v2 chat query.",
            endpoint="/api/v2/chat/query",
            user_id=effective_user_id,
            event="chat_query_accepted",
            request_id=request_id,
            attributes={
                "auth_user_id": effective_user_id,
                "org_id": auth_context.org_id,
                "role": effective_role,
                "locale": str(body["locale"]),
                "session_id": str(body["session_id"]),
            },
        )
        payload = ChatQueryRequestPayload(
            user_id=effective_user_id,
            session_id=str(body["session_id"]),
            question=str(body["question"]),
            locale=Locale(str(body["locale"])),
            role=UserRole(effective_role),
        )
        _query_started_at = __import__("time").perf_counter()
        api_envelope = chatbi_application.handle_chat_query(
            payload,
            trace_id=legacy_trace_id_from_v2(trace_id),
            idempotency_key=idempotency_key,
            org_id=auth_context.org_id,
        )
        _query_latency_ms = int((__import__("time").perf_counter() - _query_started_at) * 1000)
        if active_query_audit_log is not None:
            try:
                _data = api_envelope.data or {}
                _tbl = _data.get("table_result") if isinstance(_data, dict) else None
                _sql_rows = 0
                if _tbl is not None:
                    if isinstance(_tbl, dict):
                        _sql_rows = len(_tbl.get("rows", []))
                    elif hasattr(_tbl, "rows"):
                        _sql_rows = len(_tbl.rows or [])
                _evs = _data.get("evidence_list", []) if isinstance(_data, dict) else []
                if not isinstance(_evs, (list, tuple)):
                    _evs = []
                _ev_simple = [
                    {"source_id": e.get("source_id", ""), "title": e.get("title", ""), "snippet": (e.get("snippet") or "")[:200]}
                    for e in _evs if isinstance(e, dict)
                ]
                _blocked = api_envelope.code not in (0, ApiErrorCode.RATE_LIMITED) and any(
                    "blocked" in (w.get("message") or "").lower() or "block" in (w.get("code") or "").lower()
                    for w in (api_envelope.warnings or [])
                    if isinstance(w, dict)
                )
                _status = (
                    "blocked" if _blocked
                    else "succeeded" if api_envelope.code == 0
                    else "failed"
                )
                active_query_audit_log.save(QueryAuditRecord(
                    trace_id=trace_id,
                    request_id=request_id,
                    user_id=effective_user_id,
                    org_id=auth_context.org_id,
                    session_id=str(body["session_id"]),
                    role=effective_role,
                    question=str(body["question"]),
                    answer_text=_data.get("answer_text") if isinstance(_data, dict) else None,
                    status=_status,
                    error_code=str(api_envelope.code) if api_envelope.code != 0 else None,
                    blocked=_blocked,
                    sql_row_count=_sql_rows,
                    rag_doc_count=len(_evs),
                    has_chart=bool(isinstance(_data, dict) and _data.get("chart_spec")),
                    evidence_json=__import__("json").dumps(_ev_simple),
                    latency_ms=_query_latency_ms,
                    finished_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                ))
            except Exception:
                pass

        if api_envelope.code == 0:
            active_request_metadata_store.mark_succeeded(trace_id)
            if active_runtime_query_result_store is not None:
                runtime_record = runtime_query_result_record_from_response(
                    trace_id=trace_id,
                    session_id=str(body["session_id"]),
                    user_id=effective_user_id,
                    org_id=auth_context.org_id,
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
            user_id=effective_user_id,
            event=event,
            request_id=request_id,
            attributes={
                "auth_user_id": effective_user_id,
                "org_id": auth_context.org_id,
                "api_code": str(api_envelope.code),
                "warning_count": len(api_envelope.warnings),
            },
        )
        response = v2_response_from_api_envelope(
            api_envelope,
            request_id=request_id,
            trace_id=trace_id,
        )
        if api_envelope.code is ApiErrorCode.RATE_LIMITED:
            response["data"] = api_envelope.data
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
        auth_context, auth_error = authenticate_v2(
            authorization,
            lookup_trace_id,
            active_request_id,
            required_permission="chat:history:read:self",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)
        effective_user_id = user_id if authorization == "Bearer test-token" else auth_context.user_id

        api_envelope = chatbi_application.handle_chat_history(
            user_id=effective_user_id,
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
        auth_context, auth_error = authenticate_v2(authorization, lookup_trace_id, active_request_id)
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        api_envelope = chatbi_application.handle_metrics_catalog(
            user_id=user_id if authorization == "Bearer test-token" else auth_context.user_id,
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
        auth_context, auth_error = authenticate_v2(authorization, lookup_trace_id, active_request_id)
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        api_envelope = chatbi_application.handle_datasets_catalog(
            user_id=user_id if authorization == "Bearer test-token" else auth_context.user_id,
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
        auth_context, auth_error = authenticate_v2(authorization, lookup_trace_id, active_request_id)
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        api_envelope = chatbi_application.handle_health_check(
            user_id=user_id if authorization == "Bearer test-token" else auth_context.user_id,
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
        auth_context, auth_error = authenticate_v2(
            authorization,
            lookup_trace_id,
            active_request_id,
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

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
        auth_context, auth_error = authenticate_v2(
            authorization,
            lookup_trace_id,
            active_request_id,
            required_permission="query:read:self",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        api_envelope = chatbi_application.handle_query_detail(
            trace_id=legacy_trace_id_from_v2(trace_id),
            user_id=user_id if authorization == "Bearer test-token" else auth_context.user_id,
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
        auth_context, auth_error = authenticate_v2(
            authorization,
            lookup_trace_id,
            active_request_id,
            required_permission="query:read:self",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        record = active_request_metadata_store.get(trace_id)
        if record is None or (
            authorization != "Bearer test-token"
            and (
                record.org_id != auth_context.org_id
                or record.user_id != auth_context.user_id
            )
        ):
            return tenant_not_found_response(
                active_request_id,
                lookup_trace_id,
                "REQUEST_NOT_FOUND",
                "Request metadata was not found for this trace id.",
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
        auth_context, auth_error = authenticate_v2(authorization, lookup_trace_id, active_request_id)
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        record = active_worker_handoff_queue.get(task_id)
        if record is None or (
            authorization != "Bearer test-token"
            and not task_visible_to_context(record, auth_context)
        ):
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
        auth_context, auth_error = authenticate_v2(
            authorization,
            body.trace_id,
            active_request_id,
            required_permission="analytics:run",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        try:
            request = body.to_domain(
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
            )
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
        auth_context, auth_error = authenticate_v2(
            authorization,
            body.trace_id,
            active_request_id,
            required_permission="analytics:run",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        try:
            request = body.to_domain(
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
            )
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
                payload={
                    "request": body.to_task_payload(
                        org_id=auth_context.org_id,
                        user_id=auth_context.user_id,
                    ),
                    "org_id": auth_context.org_id,
                    "user_id": auth_context.user_id,
                },
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
        auth_context, auth_error = authenticate_v2(authorization, trace_id, active_request_id)
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        record = active_analytics_service.result_by_trace_id(trace_id)
        if record is None or (
            authorization != "Bearer test-token"
            and record.org_id != "org_legacy"
            and record.user_id != "user_legacy"
            and (record.org_id != auth_context.org_id or record.user_id != auth_context.user_id)
        ):
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

    @app.post("/api/v2/evals/run")
    def eval_run_v2(  # pyright: ignore[reportUnusedFunction]
        body: EvalRunRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_eval_run")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="admin:eval:write",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        api_envelope = chatbi_application.handle_eval_run(
            user_id=auth_context.user_id,
            trace_id=trace_id,
            payload=body.to_payload(),
            org_id=auth_context.org_id,
        )
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=v2_generic_response_from_api_envelope(
                api_envelope,
                request_id=active_request_id,
                trace_id=trace_id,
            ),
        )

    @app.get("/api/v2/evals/{eval_run_id}")
    def eval_report_v2(  # pyright: ignore[reportUnusedFunction]
        eval_run_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_eval_report")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="admin:eval:read",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        api_envelope = chatbi_application.handle_eval_report(
            user_id=auth_context.user_id,
            trace_id=trace_id,
            eval_run_id=eval_run_id,
            org_id=auth_context.org_id,
        )
        if api_envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT:
            return tenant_not_found_response(
                active_request_id,
                trace_id,
                "EVAL_RUN_NOT_FOUND",
                "Eval run was not found.",
            )
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=v2_generic_response_from_api_envelope(
                api_envelope,
                request_id=active_request_id,
                trace_id=trace_id,
            ),
        )

    @app.get("/api/v2/release-gates/latest")
    def release_gate_latest_v2(  # pyright: ignore[reportUnusedFunction]
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_release_gate_latest")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="admin:release_gate:read",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        api_envelope = chatbi_application.handle_quality_dashboard(
            user_id=auth_context.user_id,
            trace_id=trace_id,
            org_id=auth_context.org_id,
        )
        response = v2_generic_response_from_api_envelope(
            api_envelope,
            request_id=active_request_id,
            trace_id=trace_id,
        )
        data = api_envelope.data if isinstance(api_envelope.data, Mapping) else {}
        release_gate = data.get("release_gate")
        if release_gate is None:
            response["data"] = {"release_gate": None}
        else:
            response["data"] = release_gate
        return JSONResponse(
            status_code=status_code_for_envelope(api_envelope),
            content=response,
        )

    @app.get("/api/v2/admin/observability/summary")
    def admin_observability_summary_v2(  # pyright: ignore[reportUnusedFunction]
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(
            request_id,
            "req_admin_observability_summary",
        )
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)
        permission_error = require_v2_permissions(
            auth_context,
            trace_id,
            active_request_id,
            (
                "admin:trace:read",
                "admin:eval:read",
                "admin:release_gate:read",
                "admin:audit:read",
            ),
        )
        if permission_error is not None:
            return permission_error

        _ready, readiness_payload = current_readiness_payload()
        chatbi_application.record_api_audit(
            trace_id=trace_id,
            user_id=auth_context.user_id,
            endpoint="/api/v2/admin/observability/summary",
            status_code=200,
        )
        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": admin_observability_summary_payload(
                    runtime_config=active_runtime_config,
                    readiness_payload=readiness_payload,
                    application=chatbi_application,
                    request_metadata_store=active_request_metadata_store,
                    runtime_query_result_store=active_runtime_query_result_store,
                    guardrail_audit_log=active_guardrail_audit_log_v2,
                    embedding_vector_rag_service=active_embedding_vector_rag_service,
                    org_id=auth_context.org_id,
                    user_id=auth_context.user_id,
                ),
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/admin/query-audit")
    def admin_query_audit_list(  # pyright: ignore[reportUnusedFunction]
        user_id: str | None = None,
        status: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 50,
        offset: int = 0,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        import datetime as _dt
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_admin_query_audit")
        auth_context, auth_error = authenticate_v2(authorization, trace_id, active_request_id)
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)
        if "admin:audit:read" not in (auth_context.permissions or []):
            return cast(JSONResponse, v2_error_response(
                request_id=active_request_id, trace_id=trace_id,
                code="AUTH_FORBIDDEN", message="Admin audit permission required.", status_code=403,
            ))
        if active_query_audit_log is None:
            return JSONResponse(status_code=200, content={
                "trace_id": trace_id, "request_id": active_request_id,
                "data": {"items": [], "total": 0, "stats": {}}, "warnings": [], "error": None,
            })
        from_dt = _dt.datetime.fromisoformat(from_date) if from_date else None
        to_dt = _dt.datetime.fromisoformat(to_date) if to_date else None
        records = active_query_audit_log.list_recent(
            org_id=auth_context.org_id, user_id=user_id or None,
            status=status or None, from_dt=from_dt, to_dt=to_dt,
            limit=min(limit, 200), offset=offset,
        )
        total = active_query_audit_log.count_recent(
            org_id=auth_context.org_id, user_id=user_id or None,
            status=status or None, from_dt=from_dt, to_dt=to_dt,
        )
        stats = active_query_audit_log.stats(org_id=auth_context.org_id)
        return JSONResponse(status_code=200, content={
            "trace_id": trace_id, "request_id": active_request_id,
            "data": {
                "items": [r.to_dict() for r in records],
                "total": total,
                "stats": stats,
            },
            "warnings": [], "error": None,
        })

    @app.get("/api/v2/admin/query-audit/{audit_trace_id}")
    def admin_query_audit_detail(  # pyright: ignore[reportUnusedFunction]
        audit_trace_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_admin_query_audit_detail")
        auth_context, auth_error = authenticate_v2(authorization, trace_id, active_request_id)
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)
        if "admin:audit:read" not in (auth_context.permissions or []):
            return cast(JSONResponse, v2_error_response(
                request_id=active_request_id, trace_id=trace_id,
                code="AUTH_FORBIDDEN", message="Admin audit permission required.", status_code=403,
            ))
        if active_query_audit_log is None:
            return JSONResponse(status_code=404, content={"error": "Audit log not available."})
        record = active_query_audit_log.get(audit_trace_id)
        if record is None:
            return JSONResponse(status_code=404, content={"error": "Record not found."})
        return JSONResponse(status_code=200, content={
            "trace_id": trace_id, "request_id": active_request_id,
            "data": record.to_dict(), "warnings": [], "error": None,
        })

    @app.post("/api/v2/documents/index")
    def document_index_v2(  # pyright: ignore[reportUnusedFunction]
        body: DocumentIndexRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        active_trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_document_index")
        auth_context, auth_error = authenticate_v2(
            authorization,
            active_trace_id,
            active_request_id,
            required_permission="documents:index",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

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
            cache_key = ("v2_documents_index", auth_context.org_id, idempotency_key)
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
                payload=body.to_task_payload(
                    org_id=auth_context.org_id,
                    user_id=auth_context.user_id,
                ),
            )
        )
        vector_result = index_document_into_vector_rag(
            service=active_embedding_vector_rag_service,
            body=body,
            trace_id=legacy_trace_id_from_v2(active_trace_id),
            org_id=auth_context.org_id,
            user_id=auth_context.user_id,
        )
        if vector_result is not None:
            task = active_worker_handoff_queue.mark_succeeded(task.task_id, vector_result)
        if idempotency_key is not None:
            document_index_idempotency_cache[
                ("v2_documents_index", auth_context.org_id, idempotency_key)
            ] = (
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
        auth_context, auth_error = authenticate_v2(
            authorization,
            lookup_trace_id,
            active_request_id,
            required_permission="query:read:self",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        record = (
            active_runtime_query_result_store.get(trace_id)
            if active_runtime_query_result_store is not None
            else None
        )
        if record is None or (
            authorization != "Bearer test-token"
            and (
                record.org_id != auth_context.org_id
                or record.user_id != auth_context.user_id
            )
        ):
            return tenant_not_found_response(
                active_request_id,
                lookup_trace_id,
                "QUERY_RESULT_NOT_FOUND",
                "Runtime query result was not found for this trace id.",
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
        auth_context, auth_error = authenticate_v2(
            authorization,
            lookup_trace_id,
            active_request_id,
            required_permission="admin:trace:read",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

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
        if (
            request_record is None and query_result_record is None and guardrail_record is None
        ) or (
            authorization != "Bearer test-token"
            and request_record is not None
            and request_record.org_id != auth_context.org_id
        ):
            return tenant_not_found_response(
                active_request_id,
                lookup_trace_id,
                "GOVERNANCE_TRACE_NOT_FOUND",
                "Governance trace evidence was not found for this trace id.",
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
        auth_context, active_trace_id, rejected = authenticate_v1(
            "/api/v1/documents/index",
            trace_id,
            authorization,
            required_permission="documents:index",
        )
        if rejected is not None:
            return rejected
        assert auth_context is not None
        effective_user_id = (
            user_id if authorization == "Bearer test-token" else auth_context.user_id
        )

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
                user_id=effective_user_id,
                endpoint="/api/v1/documents/index",
                status_code=400,
                error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            )
            return response_from_envelope(response, status_code=400)

        body_fingerprint = body.idempotency_fingerprint()
        if idempotency_key is not None:
            cache_key = ("v1_documents_index", auth_context.org_id, idempotency_key)
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
                        user_id=effective_user_id,
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
                    user_id=effective_user_id,
                    endpoint="/api/v1/documents/index",
                    status_code=202,
                )
                return response_from_envelope(response, status_code=202)

        task = active_worker_handoff_queue.enqueue(
            AsyncTaskRequest(
                trace_id=active_trace_id,
                kind=AsyncTaskKind.INDEXING,
                payload=body.to_task_payload(org_id=auth_context.org_id),
            )
        )
        vector_result = index_document_into_vector_rag(
            service=active_embedding_vector_rag_service,
            body=body,
            trace_id=active_trace_id,
            org_id=auth_context.org_id,
            user_id=effective_user_id,
        )
        if vector_result is not None:
            task = active_worker_handoff_queue.mark_succeeded(task.task_id, vector_result)
        if idempotency_key is not None:
            document_index_idempotency_cache[
                ("v1_documents_index", auth_context.org_id, idempotency_key)
            ] = DocumentIndexIdempotencyEntry(
                body_fingerprint=body_fingerprint,
                task=task,
            )
        response = envelope(
            data=document_index_response_data(body, task),
            trace_id=active_trace_id,
        )
        chatbi_application.record_api_audit(
            trace_id=active_trace_id,
            user_id=effective_user_id,
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
        auth_context, _, rejected = authenticate_v1(
            f"/api/v1/audit/{trace_id}",
            request_trace_id,
            authorization,
            required_permission="admin:audit:read",
        )
        if rejected is not None:
            return rejected
        assert auth_context is not None
        effective_user_id = (
            user_id if authorization == "Bearer test-token" else auth_context.user_id
        )

        envelope = chatbi_application.handle_audit_detail(
            trace_id=trace_id,
            user_id=effective_user_id,
        )
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/observability/traces/{trace_id}")
    def observability_trace_detail(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        auth_context, _, rejected = authenticate_v1(
            f"/api/v1/observability/traces/{trace_id}",
            request_trace_id,
            authorization,
            required_permission="admin:trace:read",
        )
        if rejected is not None:
            return rejected
        assert auth_context is not None
        effective_user_id = (
            user_id if authorization == "Bearer test-token" else auth_context.user_id
        )

        envelope = chatbi_application.handle_observability_trace_detail(
            trace_id=trace_id,
            user_id=effective_user_id,
        )
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/quality/dashboard")
    def quality_dashboard(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        auth_context, active_trace_id, rejected = authenticate_v1(
            "/api/v1/quality/dashboard",
            trace_id,
            authorization,
            required_permission="admin:release_gate:read",
        )
        if rejected is not None:
            return rejected
        assert auth_context is not None
        effective_user_id = (
            user_id if authorization == "Bearer test-token" else auth_context.user_id
        )

        envelope = chatbi_application.handle_quality_dashboard(
            user_id=effective_user_id,
            trace_id=active_trace_id,
            org_id=auth_context.org_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.post("/api/v1/evals/run")
    def eval_run(  # pyright: ignore[reportUnusedFunction]
        body: EvalRunRequestBody,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        auth_context, active_trace_id, rejected = authenticate_v1(
            "/api/v1/evals/run",
            trace_id,
            authorization,
            required_permission="admin:eval:write",
        )
        if rejected is not None:
            return rejected
        assert auth_context is not None
        effective_user_id = (
            user_id if authorization == "Bearer test-token" else auth_context.user_id
        )

        envelope = chatbi_application.handle_eval_run(
            user_id=effective_user_id,
            trace_id=active_trace_id,
            payload=body.to_payload(),
            org_id=auth_context.org_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/evals/{eval_run_id}")
    def eval_report(  # pyright: ignore[reportUnusedFunction]
        eval_run_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        auth_context, active_trace_id, rejected = authenticate_v1(
            f"/api/v1/evals/{eval_run_id}",
            trace_id,
            authorization,
            required_permission="admin:eval:read",
        )
        if rejected is not None:
            return rejected
        assert auth_context is not None
        effective_user_id = (
            user_id if authorization == "Bearer test-token" else auth_context.user_id
        )

        envelope = chatbi_application.handle_eval_report(
            user_id=effective_user_id,
            trace_id=active_trace_id,
            eval_run_id=eval_run_id,
            org_id=auth_context.org_id,
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
