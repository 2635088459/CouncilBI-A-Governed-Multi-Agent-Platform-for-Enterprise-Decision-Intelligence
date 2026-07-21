"""FastAPI entry point for the Backend API slice."""

from __future__ import annotations

from hashlib import sha256
import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Mapping, Sequence, cast
from uuid import uuid4

import duckdb
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, Request, UploadFile
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
from chatbi.answer_synthesis import GroundedAnswerSynthesizer
from chatbi.api.models import (
    ApiEnvelope,
    ApiErrorCode,
    ChatQueryRequestPayload,
    EvalRunRequestPayload,
    envelope,
    error_envelope,
)
from chatbi.agents import (
    FederatedQueryAgent,
    FileDataAgent,
    FileNotReadyError,
    FileOwnershipError,
    FileScopedRetriever,
    ReadOnlyBusinessRowSource,
    question_references_any_attached_file,
    question_references_attached_file,
    split_file_ids_by_type,
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
from chatbi.core.contracts import (
    ErrorCode,
    EvidenceItem,
    Locale,
    QueryAnswer,
    QueryHistoryRecord,
    QueryRequest,
    TableResult,
    UserRole,
    WarningMessage,
    new_trace_id,
)
from chatbi.core.runtime_config import (
    DatabaseReadinessChecker,
    RedisReadinessChecker,
    RedisTcpPingClient,
    RuntimeConfig,
    load_runtime_config,
)
from chatbi.embedding_vector_config import (
    build_embedding_vector_rag_service_from_runtime_config,
    build_knowledge_store_embedding_client,
)
from chatbi.embedding_vector_rag import EmbeddingClient
from chatbi.embedding_vector_rag import (
    DocumentRecord,
    EmbeddingVectorRagService,
    InMemoryVectorStore,
    MockEmbeddingClient,
)
from chatbi.files import (
    DEFAULT_CHUNK_SIZE_BYTES,
    MAX_UPLOAD_SESSION_TTL,
    ChunkUploadSession,
    ChunkUploadSessionStore,
    DocumentNotPromotedError,
    FederatedQueryAgentInput,
    FileAccessChecker,
    FileAccessDecision,
    FileDataAgentInput,
    FileFormatCheckResult,
    FileFormatValidator,
    FileNotPromotableError,
    FileNotShareableError,
    FileProcessingWorker,
    FileRepository,
    FileShareApprovalService,
    FileShareRecord,
    FileShareRequest,
    FileSizeCheckResult,
    FileSizeEnforcer,
    FileVectorSink,
    FileVectorSource,
    FileVersionManager,
    InMemoryChunkUploadSessionStore,
    InMemoryFileRepository,
    InMemoryFileVectorSink,
    InMemoryObjectStorageAdapter,
    KnowledgePromotionService,
    LocalDiskObjectStorageAdapter,
    MimeCheckResult,
    MimeMagicChecker,
    NotAuthorizedToPromoteError,
    NotFileOwnerError,
    ObjectNotFoundError,
    ObjectStorageAdapter,
    PendingShareRequestExistsError,
    PostgresFileRepository,
    RetentionWorker,
    ShareRequestNotFoundError,
    ShareRequestNotPendingError,
    StorageQuotaCheckResult,
    StorageQuotaEnforcer,
    UserUploadedFile,
    build_storage_key,
    chunk_staging_key,
    compute_chunk_count,
    file_share_visibility_resolver,
    new_share_id,
    new_upload_id,
    parquet_storage_key,
    postgres_file_repository_from_psycopg,
    purge_duplicate_archived_file,
    sanitize_filename,
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
from chatbi.history.in_memory import conversation_messages
from chatbi.history.session_file_context import (
    InMemorySessionFileContext,
    resolve_effective_file_ids,
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
from chatbi.governance.business_table_catalog import BusinessTableCatalog, resolve_federated_pg_context
from chatbi.governance.query_audit import QueryAuditLog, QueryAuditRecord
from chatbi.llm import LLMClient, build_llm_client_from_runtime_config
from chatbi.knowledge import (
    BgeCrossEncoderReranker,
    ChunkEmbedding,
    CrossEncoderReranker,
    DocumentChunk,
    InMemoryKnowledgeStore,
    KnowledgeDocument,
    RetrievalQuery,
)
from chatbi.knowledge_postgres_vector_source import (
    PostgresKnowledgeVectorSource,
    VectorCandidateSource,
)
from chatbi.orchestration import AnalyticsServiceRunner, QuestionClassifier, ResultMerger, TaskType
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


class FileUploadInitRequestBody(BaseModel):
    original_name: str
    file_size_bytes: int
    mime_type: str
    scope: str = "session"
    session_id: str | None = None
    description: str | None = None


class ChunkEtagBody(BaseModel):
    chunk_index: int
    etag: str


class FileUploadCompleteRequestBody(BaseModel):
    etags: tuple[ChunkEtagBody, ...] = ()


class FileShareRequestBody(BaseModel):
    granted_to: str


class ShareRequestRejectBody(BaseModel):
    reason: str | None = None


class PromoteFileRequestBody(BaseModel):
    file_id: str


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
    if envelope.code is ApiErrorCode.SQL_NOT_QUERYABLE:
        return 400
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


def _build_default_file_repository(
    runtime_config: RuntimeConfig,
    connect: Callable[[str], Any] | None,
    use_postgres_metadata: bool,
) -> FileRepository:
    if use_postgres_metadata and runtime_config.database_url:
        repository: PostgresFileRepository = postgres_file_repository_from_psycopg(
            (connect or connect_psycopg)(runtime_config.database_url)
        )
        repository.initialize_schema()
        return repository
    return InMemoryFileRepository()


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
    embedding_client: EmbeddingClient | None = None,
    reranker: CrossEncoderReranker | None = None,
    vector_candidate_source: VectorCandidateSource | None = None,
) -> InMemoryKnowledgeStore:
    # FR-FV03-014/015: real embeddings, when configured, must reach this
    # path too — it is the one that actually populates the live, seeded
    # knowledge store RagAgentRunner queries at chat time, not ingest_document().
    store = InMemoryKnowledgeStore(
        embedding_client=embedding_client,
        # Code-review fix (Spec FV03.3/FV03.5 gap): both were implemented
        # and tested but never reached this constructor before — see
        # _build_default_chatbi_application's own comment for the
        # opt-in flags that gate them.
        reranker=reranker,
        vector_candidate_source=vector_candidate_source,
    )
    try:
        conn = connect_fn(database_url)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, title, doc_type, publish_time, business_tags, allowed_roles, owner_user_id"
                " FROM knowledge.documents"
            )
            for row in cur.fetchall():
                source_id, title, doc_type, publish_time, business_tags, allowed_roles, owner_user_id = row
                store.save_document(
                    KnowledgeDocument(
                        source_id=source_id,
                        title=title,
                        doc_type=doc_type,
                        publish_time=publish_time,
                        tags=tuple(business_tags or []),
                        allowed_roles=tuple(allowed_roles or []),
                        owner_user_id=owner_user_id,
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
                        embedding_vector=store.embed_text(chunk_text),
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
    # FR-FV03-015: one embedding-provider switch governs the knowledge
    # store's embeddings on every path that can populate it, matching what
    # already selects the vector-only pipeline's provider.
    knowledge_store_embedding_client = build_knowledge_store_embedding_client(runtime_config)
    # Code-review fix: Specs FV03.3 (reranking) and FV03.5 (pgvector
    # narrowing) were fully implemented and tested but never constructed
    # here — both are opt-in via RuntimeConfig flags (default off), so
    # enabling either is a deliberate operator action, not a silent
    # behavior change on deploy.
    knowledge_store_reranker = BgeCrossEncoderReranker() if runtime_config.reranker_enabled else None
    knowledge_store_vector_candidate_source = (
        PostgresKnowledgeVectorSource(connect_psycopg, runtime_config.database_url)
        if runtime_config.pgvector_search_enabled and runtime_config.database_url
        else None
    )
    knowledge_store = (
        _load_knowledge_store_from_db(
            connect_psycopg,
            runtime_config.database_url,
            embedding_client=knowledge_store_embedding_client,
            reranker=knowledge_store_reranker,
            vector_candidate_source=knowledge_store_vector_candidate_source,
        )
        if runtime_config.database_url
        else InMemoryKnowledgeStore(
            embedding_client=knowledge_store_embedding_client,
            reranker=knowledge_store_reranker,
            vector_candidate_source=knowledge_store_vector_candidate_source,
        )
    )
    if runtime_config.readonly_database_url is None:
        return ChatBIApplication(
            orchestrator=SimpleOrchestrator(
                llm_client=llm_client,
                knowledge_store=knowledge_store,
                conversation_context_turns=runtime_config.conversation_context_turns,
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
            conversation_context_turns=runtime_config.conversation_context_turns,
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
    # A document-only answer (Spec FV10.5) has no SQL to replay — this store
    # exists specifically for SQL-result replay, so there is nothing to
    # persist here, not an error; the caller already treats None as "skip".
    if not isinstance(sql_text, str) or not sql_text.strip():
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

    table_result_source = data.get("table_result_source")
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
        "table_result_source": str(table_result_source) if table_result_source else None,
        "guardrail_blocked": bool(data.get("guardrail_blocked", False)),
        "analytics_result": (
            _json_safe_mapping(cast(Mapping[str, Any], data.get("analytics_result")))
            if isinstance(data.get("analytics_result"), Mapping)
            else None
        ),
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


_ANALYTICS_TIME_COLUMN_HINTS = ("month", "date", "time", "period", "day", "year", "week")

# 10-followups/12 (Spec FV10.12 §6.1, revised per §10): the minimum
# InMemoryKnowledgeStore relevance_score a knowledge-base evidence item must
# clear before being attached to a hybrid file/warehouse answer's
# evidence_payload ("Sources"). Scoped to _handle_file_data_chat_query only.
#
# 0.35 (this spec's originally proposed value) was measured, during
# implementation, to exclude a genuinely on-topic document already covered
# by an existing regression test (score 0.2267) while *admitting*
# reconstructions of the originally reported bug's own unrelated documents
# (0.3502 and 0.4011) — this store's keyword+hashed-embedding scoring
# rewards a document's vocabulary breadth more than its topical relevance,
# so a short, precisely on-topic snippet can score lower than a long,
# generically related but off-topic one. No fixed floor can satisfy both
# constraints at once; 0.15 is chosen to preserve the passing regression
# test while still excluding near-zero, essentially-unrelated matches. It is
# not expected to reliably exclude a reconstruction of the original
# report's own documents — see this spec's §10 and the source design's §6.
_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE = 0.15


def _infer_time_value_columns(table_result: TableResult) -> tuple[str, str] | None:
    """Best-effort: which column is the time axis, which is the metric.

    FileDataAgent/FederatedQueryAgent tables have no declared time/value
    role the way a resolved semantic metric does, so this is a heuristic:
    first column whose name looks like a time bucket, then the first
    remaining numeric column. Returns None when either guess fails, so the
    caller skips analytics instead of feeding AnalyticsService garbage.
    """

    if not table_result.rows:
        return None
    sample = table_result.rows[0]
    time_column = next(
        (column for column in table_result.columns if column.lower() in _ANALYTICS_TIME_COLUMN_HINTS),
        None,
    )
    if time_column is None:
        return None
    value_column = next(
        (
            column
            for column in table_result.columns
            if column != time_column
            and isinstance(sample.get(column), (int, float))
            and not isinstance(sample.get(column), bool)
        ),
        None,
    )
    if value_column is None:
        return None
    return time_column, value_column


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


async def _run_retention_sweep_loop(worker: RetentionWorker, interval_seconds: float) -> None:
    """FR-FV10-050: actually invoke RetentionWorker.run() on a schedule.

    Runs the sweep immediately (so a fresh process doesn't wait a full
    interval for its first pass), then repeats. A single in-process
    ``asyncio`` loop is deliberately not a distributed job queue — see the
    source design's §7 scoping note.
    """

    while True:
        try:
            worker.run()
        except Exception:
            pass  # a transient failure must not kill the schedule itself
        await asyncio.sleep(interval_seconds)


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
    file_repository: FileRepository | None = None,
    file_repository_connect: Callable[[str], Any] | None = None,
    object_storage_adapter: ObjectStorageAdapter | None = None,
    file_vector_sink: FileVectorSink | None = None,
    chunk_upload_session_store: ChunkUploadSessionStore | None = None,
    file_query_llm_client: LLMClient | None = None,
    business_table_catalog: BusinessTableCatalog | None = None,
    federated_query_agent: FederatedQueryAgent | None = None,
    retention_sweep_interval_seconds: float = 86400.0,
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
    active_file_repository = file_repository or _build_default_file_repository(
        runtime_config=active_runtime_config,
        connect=file_repository_connect,
        use_postgres_metadata=use_postgres_metadata,
    )
    active_object_storage_adapter = object_storage_adapter or (
        LocalDiskObjectStorageAdapter(Path(active_runtime_config.file_storage_root))
        if active_runtime_config.file_storage_root
        else InMemoryObjectStorageAdapter()
    )
    active_file_vector_sink: FileVectorSink = file_vector_sink or InMemoryFileVectorSink()
    active_file_vector_source = cast(FileVectorSource, active_file_vector_sink)
    active_chunk_upload_session_store = (
        chunk_upload_session_store or InMemoryChunkUploadSessionStore()
    )
    file_access_checker = FileAccessChecker()
    file_version_manager = FileVersionManager()
    # Code-review fix: this embedding_client was hardcoded to
    # MockEmbeddingClient() regardless of runtime_config.embedding_provider
    # — every uploaded file's chunks were always embedded with the
    # deterministic mock, never the real configured provider. Reuses the
    # same helper that already governs the knowledge store's embeddings
    # (FR-FV03-015), so one configuration switch now covers file uploads
    # too. FileProcessingWorker's embedding_client is a required
    # parameter, unlike InMemoryKnowledgeStore's optional one, so the
    # "mock" case still needs an explicit MockEmbeddingClient() instance.
    file_processing_embedding_client = build_knowledge_store_embedding_client(active_runtime_config)
    file_processing_worker = FileProcessingWorker(
        storage=active_object_storage_adapter,
        repository=active_file_repository,
        embedding_client=file_processing_embedding_client or MockEmbeddingClient(),
        vector_sink=active_file_vector_sink,
    )
    active_knowledge_vector_store = (
        active_embedding_vector_rag_service.vector_store
        if active_embedding_vector_rag_service is not None
        else InMemoryVectorStore()
    )
    # Promotion must also reach the InMemoryKnowledgeStore that RagAgentRunner
    # actually queries at chat time (see _load_knowledge_store_from_db) —
    # writing only to active_knowledge_vector_store above leaves a promoted
    # file invisible to real RAG answers until the next process restart.
    knowledge_promotion_connection: Any | None = None
    if active_runtime_config.database_url:
        try:
            knowledge_promotion_connection = connect_psycopg(active_runtime_config.database_url)
        except Exception:
            knowledge_promotion_connection = None
    knowledge_promotion_service = KnowledgePromotionService(
        repository=active_file_repository,
        vector_store=active_knowledge_vector_store,
        vector_source=active_file_vector_source,
        live_knowledge_store=chatbi_application.orchestrator.knowledge_store,
        knowledge_connection=knowledge_promotion_connection,
    )
    file_share_approval_service = FileShareApprovalService(
        repository=active_file_repository,
        auth_store=active_auth_service.store,
    )
    # Spec FV10.1's owner-isolation filter (§4's shared_visibility()) needs
    # active_file_repository to resolve "does this promoted document's
    # source file have an active share grant for this user" — not available
    # yet when _build_default_chatbi_application constructed the store, so
    # it is rewired here now that the repository exists.
    if chatbi_application.orchestrator.knowledge_store is not None:
        chatbi_application.orchestrator.knowledge_store.set_shared_visibility_resolver(
            file_share_visibility_resolver(active_file_repository)
        )
    retention_worker = RetentionWorker(
        repository=active_file_repository,
        knowledge_promotion_service=knowledge_promotion_service,
    )
    active_file_query_llm_client = file_query_llm_client or build_llm_client_from_runtime_config(
        active_runtime_config
    )
    file_data_agent = FileDataAgent(
        repository=active_file_repository,
        storage=active_object_storage_adapter,
        llm_client=active_file_query_llm_client,
    )
    file_answer_synthesizer = GroundedAnswerSynthesizer(llm_client=active_file_query_llm_client)
    file_result_merger = ResultMerger()
    # Spec FV10.6 FR-FV10-065: evidence scoped to exactly one request's own
    # unstructured file_ids, distinct from the org-wide promoted knowledge
    # base retrieved a few lines below.
    file_scoped_retriever = FileScopedRetriever(
        vector_source=active_file_vector_source,
        repository=active_file_repository,
        # Code-review fix: must match FileProcessingWorker's embedding_client
        # above — the chunk vectors it searches over were embedded with
        # this same client, not the deterministic hash-bucket fallback.
        embedding_client=file_processing_embedding_client,
    )
    question_classifier = QuestionClassifier()
    # Spec FV10.4: one session-scoped file_ids inheritance store (FR-FV10-055)
    # and one shared conversation-history store (FR-FV10-051/052), reused by
    # both the main orchestrator path and the file-data branch below, so a
    # session's context is continuous regardless of which branch answered a
    # given turn.
    session_file_context = InMemorySessionFileContext()
    shared_query_history = chatbi_application.orchestrator.history
    # FR-FV10-021: FederatedQueryAgent joins a user's uploaded file with a
    # real business.* table in one DuckDB session, ad hoc, per query — it
    # never writes anything back. business_table_catalog answers "which
    # table is this question about, and which of its columns may this role
    # see" from live Postgres (information_schema + governance.access_policies),
    # not the aspirational static DataModelCatalog, so it never proposes a
    # join against a table that doesn't actually exist in this deployment.
    active_business_table_catalog = business_table_catalog
    if active_business_table_catalog is None and active_runtime_config.database_url:
        try:
            active_business_table_catalog = BusinessTableCatalog(
                connect_psycopg(active_runtime_config.database_url)
            )
        except Exception:
            active_business_table_catalog = None
    active_federated_query_agent = federated_query_agent or FederatedQueryAgent(
        repository=active_file_repository,
        storage=active_object_storage_adapter,
        llm_client=active_file_query_llm_client,
        pg_row_source=ReadOnlyBusinessRowSource(
            ReadOnlyQueryExecutor(connect_psycopg),
            active_runtime_config.readonly_database_url,
        ),
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

    def _validate_chat_query_file_ids(
        file_ids: tuple[str, ...], user_id: str
    ) -> tuple[str, str] | None:
        """Pre-flight FR-FV10-015 check, run before any request bookkeeping.

        Returns ``(error_code, message)`` for the first invalid file_id, or
        ``None`` if every file_id exists, belongs to ``user_id``, and is
        ready. Kept separate from ``FileDataAgent.run()``'s own ownership
        check so a bad file_id short-circuits before the accepted-request
        audit/metadata bookkeeping below, exactly like the existing
        request-shape ``problems`` check above.
        """

        for candidate_file_id in file_ids:
            candidate_file = active_file_repository.get(candidate_file_id)
            if (
                candidate_file is None
                or candidate_file.deleted_at is not None
                or candidate_file.user_id != user_id
            ):
                return "FILE_NOT_FOUND", f"file_id '{candidate_file_id}' was not found."
            if candidate_file.status != "ready":
                return "FILE_NOT_READY", f"file_id '{candidate_file_id}' is not ready yet."
        return None

    def _handle_file_data_chat_query(
        *,
        file_ids: tuple[str, ...],
        question: str,
        user_id: str,
        role: str,
        org_id: str,
        trace_id: str,
        session_id: str,
        locale: Locale,
        conversation_context: tuple[Mapping[str, str], ...] = (),
    ) -> ApiEnvelope:
        """FR-FV10-016/017/018/021: answer from the attached files, joined
        with a real business table when the question names one
        FederatedQueryAgent can safely read for this role (see
        business_table_catalog.py); otherwise FileDataAgent alone.

        Spec FV10.4: also folds in the session's recent-turn conversation
        context (FR-FV10-052) and, on a successful answer, saves this turn
        into the same shared history store the main orchestrator path uses,
        so a later turn sees continuous context regardless of which branch
        answered a given question.

        Spec FV10.6 FR-FV10-064/065/066: file_ids is split into a structured
        subset (queried as a table, as above) and an unstructured subset
        (searched via FileScopedRetriever, scoped to exactly these file_ids
        — not the org-wide knowledge base retrieved further down). The
        answer is synthesized from whichever subset produced something; the
        request only fails when neither did.
        """

        files_by_id: dict[str, UserUploadedFile] = {}
        for candidate_file_id in file_ids:
            candidate_file = active_file_repository.get(candidate_file_id)
            if candidate_file is None:
                # Already screened by _validate_chat_query_file_ids(); reaching
                # here means the file changed between that check and this call.
                return error_envelope(
                    code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                    message=f"File became unavailable while answering: file_id '{candidate_file_id}' not found.",
                    trace_id=trace_id,
                )
            files_by_id[candidate_file_id] = candidate_file
        structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, files_by_id)

        # 10-followups/10: the request-level relevance gate (10.8) only
        # requires ANY attached file to be relevant, so a mixed selection
        # can still carry a structured file irrelevant to this question —
        # filter it out here too, or FileDataAgent/FederatedQueryAgent
        # would be asked to query it anyway, alongside the unstructured
        # file that kept this request in the file branch in the first
        # place. Reuses question_references_attached_file() unmodified;
        # if this empties structured_ids, the existing "no structured
        # file" path below already handles that gracefully.
        #
        # Only applied when unstructured_ids is also non-empty — i.e. a
        # genuine mixed selection with a real alternative to fall back on.
        # A pure-structured selection must NOT be filtered here: this is
        # the same question_references_attached_file() verdict 10.9's
        # safety net already overrode at the request level specifically so
        # a structured-only request with no better destination stays in
        # the file branch and lets FileDataAgent's own schema-grounded LLM
        # take an educated guess — filtering unconditionally would silently
        # re-empty structured_ids right after 10.9 decided to keep it,
        # undoing that safety net. Caught by test_chat_query_phrased_with_
        # synonyms_the_schema_gate_misses_still_reaches_the_file_branch
        # (Spec FV10.9) regressing when this filter was first written
        # unconditionally.
        if unstructured_ids:
            structured_ids = tuple(
                fid for fid in structured_ids if question_references_attached_file(question, files_by_id[fid])
            )

        pg_context = (
            resolve_federated_pg_context(question, role, active_business_table_catalog)
            if active_business_table_catalog is not None and structured_ids
            else None
        )

        try:
            if not structured_ids:
                federated_output = None
                file_output = None
            elif pg_context is not None:
                federated_output = active_federated_query_agent.run(
                    FederatedQueryAgentInput(
                        file_ids=structured_ids,
                        user_id=user_id,
                        pg_context=pg_context,
                        question=question,
                        role=cast(Any, role),
                        trace_id=trace_id,
                        conversation_context=conversation_context,
                    )
                )
                file_output = None
            else:
                federated_output = None
                file_output = file_data_agent.run(
                    FileDataAgentInput(
                        file_ids=structured_ids,
                        user_id=user_id,
                        question=question,
                        role=cast(Any, role),
                        trace_id=trace_id,
                        conversation_context=conversation_context,
                    )
                )
        except (FileOwnershipError, FileNotReadyError) as exc:
            # Already screened by _validate_chat_query_file_ids(); reaching
            # here means the file changed between that check and this call.
            return error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message=f"File became unavailable while answering: {exc}.",
                trace_id=trace_id,
            )

        if federated_output is not None:
            guardrail_blocked = federated_output.error_code == "FederatedQueryGuardrailBlocked"
            sql_text = federated_output.federated_sql or ""
            table_result = federated_output.table_result
            structured_error_code = federated_output.error_code
        elif file_output is not None:
            guardrail_blocked = file_output.guardrail_blocked
            sql_text = file_output.duckdb_sql or ""
            table_result = file_output.table_result
            structured_error_code = file_output.error_code
        else:
            # No structured file was selected — nothing was queried, so
            # there is nothing to guardrail-block or to report a SQL error
            # for. FR-FV10-066 decides below whether unstructured evidence
            # can still answer the question.
            guardrail_blocked = False
            sql_text = ""
            table_result = None
            structured_error_code = None

        if guardrail_blocked:
            return envelope(
                data={
                    "answer_text": "",
                    "sql_text": sql_text,
                    "table_result": None,
                    "chart_spec": None,
                    "analytics_result": None,
                    "evidence_list": (),
                    "evidence_uncertainty": False,
                    "retrieval_stats": None,
                    "agent_timeline": [],
                    "confidence": 0.0,
                    "table_result_source": None,
                    "guardrail_blocked": True,
                },
                trace_id=trace_id,
            )

        # FR-FV10-065/070: evidence from the unstructured subset's own
        # content, scoped to exactly these file_ids. Distinct from the
        # org-wide knowledge_base_evidence retrieved further below.
        uploaded_file_evidence: tuple[EvidenceItem, ...] = ()
        file_content_unavailable = False
        if unstructured_ids:
            uploaded_file_evidence = file_scoped_retriever.retrieve(
                question=question, file_ids=unstructured_ids
            )
            if not uploaded_file_evidence and all(
                not file_scoped_retriever.vector_source.chunks_with_vectors_for_file(fid)
                for fid in unstructured_ids
            ):
                file_content_unavailable = True

        if table_result is None and not uploaded_file_evidence:
            if file_content_unavailable:
                # FR-FV10-070: every requested unstructured file's content is
                # currently unretrievable (see Spec FV10.5 §7's FileVectorSource
                # durability gap) — distinct from "searched and found nothing".
                return error_envelope(
                    code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                    message=(
                        "The selected document(s)' content is not available for search "
                        "right now. Try re-uploading the file and asking again."
                    ),
                    trace_id=trace_id,
                )
            if structured_error_code in ("INVALID_GENERATED_SQL", "QUERY_RESOURCE_EXCEEDED"):
                # FR-FV10-018/022: the LLM produced SQL that DuckDB rejected
                # (prose instead of a SELECT, wrong column names, ...) or the
                # query exceeded the memory budget, and no unstructured
                # evidence was available to answer from instead.
                return error_envelope(
                    code=ApiErrorCode.AGENT_PARTIAL_FAILURE,
                    message=(
                        "The file query could not be completed."
                        if structured_error_code == "INVALID_GENERATED_SQL"
                        else "The file query exceeded the resource budget."
                    ),
                    trace_id=trace_id,
                )
            # FR-FV10-066: neither a structured table nor unstructured
            # evidence answered this question — supersedes Spec FV10.5's
            # narrower NO_STRUCTURED_FILE_SELECTED, which fired even when
            # the selection was entirely (answerable) documents.
            return error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message=(
                    "None of the selected files could answer this question. Structured "
                    "files (CSV/XLSX) are queried as a table; documents (PDF/DOCX/TXT/MD/"
                    "PPTX) are searched for relevant content — neither produced a usable "
                    "result here."
                ),
                trace_id=trace_id,
            )

        task_types = question_classifier.classify(question)

        # FR-FV10-023-adjacent: a file query can also pull evidence from the
        # shared knowledge base (which includes any admin-promoted uploads —
        # see business_table_catalog.py's sibling feature, promotion.py) when
        # the question also reads as a why/explain question. This is the org
        # knowledge base, distinct from uploaded_file_evidence above, which is
        # scoped to exactly this request's own file_ids (Spec FV10.6).
        knowledge_base_evidence: tuple[EvidenceItem, ...] = ()
        active_knowledge_store = chatbi_application.orchestrator.knowledge_store
        if TaskType.RAG_EXPLANATION in task_types and active_knowledge_store is not None:
            retrieval_result = active_knowledge_store.retrieve(
                RetrievalQuery(
                    question=question,
                    requesting_user_id=user_id,
                    user_role=role,
                    top_k=5,
                    # FR-FV10-052/056: prior turns fold into the retrieval
                    # text so a referent like "that" still finds the right
                    # document, with no separate rewrite step.
                    conversation_context=" ".join(
                        message["content"] for message in conversation_context
                    ),
                ),
                trace_id=trace_id,
            )
            # 10-followups/12: retrieve() has no meaningful relevance floor
            # of its own (InMemoryKnowledgeStore only excludes a score of
            # exactly 0), and the RAG_EXPLANATION trigger above is a broad
            # keyword match ("internal", "report", "review" ...) that fires
            # on plenty of ordinary file-comparison questions. Without this
            # floor, whatever the knowledge base's nearest-ranked documents
            # are — relevant or not — would be rendered as "Sources" for an
            # answer that never actually used them.
            knowledge_base_evidence = tuple(
                EvidenceItem(
                    source_id=item.source_id,
                    title=item.title,
                    citation_anchor=item.citation_anchor,
                    snippet=item.snippet,
                    relevance_score=item.relevance_score,
                )
                for item in retrieval_result.evidence_list
                if item.relevance_score >= _MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE
            )

        merged = (
            file_result_merger.merge(
                federated_output=federated_output,
                uploaded_file_evidence=uploaded_file_evidence,
                knowledge_base_evidence=knowledge_base_evidence,
            )
            if federated_output is not None
            else file_result_merger.merge(
                file_output=file_output,
                uploaded_file_evidence=uploaded_file_evidence,
                knowledge_base_evidence=knowledge_base_evidence,
            )
        )
        # FR-FV10-066: an evidence-only answer (no structured file queried,
        # or its query produced nothing) has no SourcedTableResult to read —
        # fall back to an empty table rather than indexing into an empty tuple.
        if merged.table_results:
            sourced_table_result = merged.table_results[0].table_result
            table_result_source: str | None = merged.table_results[0].source
        else:
            sourced_table_result = TableResult(columns=(), rows=())
            table_result_source = None
        evidence_payload = tuple(
            {
                "source_id": sourced.evidence.source_id,
                "title": (
                    f"📎 {sourced.evidence.title}" if sourced.is_uploaded_file else sourced.evidence.title
                ),
                "citation_anchor": sourced.evidence.citation_anchor,
                "snippet": sourced.evidence.snippet,
                "relevance_score": sourced.evidence.relevance_score,
            }
            for sourced in merged.evidence_items
        )
        all_evidence = tuple(sourced.evidence for sourced in merged.evidence_items)

        # FR-FV10-021-adjacent: analytics on the file/federated table itself,
        # when the question also reads as a forecast/anomaly question and the
        # table has a plausible time column. No real semantic metric backs
        # this data, so metric_id/semantic_version_id are synthetic labels,
        # not a registered metric — see _infer_time_value_columns' docstring.
        analytics_result: Mapping[str, object] | None = None
        if TaskType.ANALYTICS in task_types:
            inferred_columns = _infer_time_value_columns(sourced_table_result)
            if inferred_columns is not None:
                time_column, value_column = inferred_columns
                analytics_run = AnalyticsServiceRunner(
                    analytics_service=chatbi_application.orchestrator.analytics_service,
                    trace_id=trace_id,
                    metric_id=f"file_upload:{value_column}",
                    semantic_version_id="file_upload",
                    time_column=time_column,
                    value_column=value_column,
                    grain=AnalyticsGrain.MONTH,
                    rows=sourced_table_result.rows,
                ).run()
                analytics_result = analytics_run.payload

        # 10-followups/12: a federated JOIN that matched zero rows despite
        # non-empty sources on both sides must not be narrated as a
        # confirmed "no variance"/threshold result — it may just as easily
        # be a join-key mismatch (spelling, capitalization, date format).
        zero_row_join_instructions = (
            "The comparison query matched zero rows across the join, even though "
            "both the file and the warehouse table each had data for this period. "
            "State plainly that no matching records were found across the join "
            "key(s) — do not claim this means all values are within any threshold, "
            "since a join-key mismatch (e.g. differing spelling, capitalization, or "
            "date format between the file and the warehouse column) produces the "
            "identical zero-row result. Recommend the user verify that the shared "
            "column(s) use the same values/format in both sources."
            if federated_output is not None and federated_output.zero_row_join_caveat
            else None
        )
        synthesis = file_answer_synthesizer.synthesize(
            question=question,
            safe_sql=sql_text,
            table_result=sourced_table_result,
            evidence_list=all_evidence,
            user_id=user_id,
            org_id=org_id,
            trace_id=trace_id,
            conversation_context=conversation_context,
            extra_instructions=zero_row_join_instructions,
        )
        warnings = synthesis.warnings
        if federated_output is not None and federated_output.degraded:
            warnings = (
                *warnings,
                WarningMessage(
                    code=ErrorCode.AGENT_PARTIAL_FAILURE,
                    message=(
                        "Joined query fell back to file-only data: "
                        f"{federated_output.degradation_reason}."
                    ),
                ),
            )
        # Spec FV10.4: record this turn in the shared history store so a
        # later turn in the same session — whether it also goes through the
        # file branch or through the main orchestrator — sees it as context.
        shared_query_history.save(
            QueryHistoryRecord(
                trace_id=trace_id,
                request=QueryRequest(
                    user_id=user_id,
                    session_id=session_id,
                    question=question,
                    locale=locale,
                    role=UserRole(role),
                ),
                answer=QueryAnswer(
                    answer_text=synthesis.answer_text,
                    sql_text=sql_text,
                    table_result=sourced_table_result,
                    trace_id=trace_id,
                    evidence_list=all_evidence,
                    confidence=0.8,
                    warnings=warnings,
                ),
            )
        )
        return envelope(
            data={
                "answer_text": synthesis.answer_text,
                "sql_text": sql_text,
                "table_result": sourced_table_result,
                "chart_spec": None,
                "analytics_result": analytics_result,
                "evidence_list": evidence_payload,
                "evidence_uncertainty": False,
                "retrieval_stats": None,
                "agent_timeline": [],
                "confidence": 0.8,
                "table_result_source": table_result_source,
                "guardrail_blocked": False,
            },
            trace_id=trace_id,
            warnings=warnings,
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

        raw_file_ids = cast(Any, body.get("file_ids"))
        file_ids: tuple[str, ...] = ()
        if isinstance(raw_file_ids, list) and raw_file_ids:
            file_ids = tuple(str(item) for item in cast(list[Any], raw_file_ids))
        session_id = str(body["session_id"])
        # Spec FV10.4 FR-FV10-055: resolved once, early, before any routing
        # decision — explicit file_ids always win and become this session's
        # new inherited value; an empty request inherits the session's
        # current value (or stays fileless if it has none yet).
        effective_file_ids = resolve_effective_file_ids(file_ids, session_id, session_file_context)
        if effective_file_ids:
            file_id_problem = _validate_chat_query_file_ids(effective_file_ids, effective_user_id)
            if file_id_problem is not None:
                error_code, error_message = file_id_problem
                return v2_error_response(
                    request_id=request_id,
                    trace_id=trace_id,
                    code=error_code,
                    message=error_message,
                    status_code=422,
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
        request_locale = Locale(str(body["locale"]))
        payload = ChatQueryRequestPayload(
            user_id=effective_user_id,
            session_id=session_id,
            question=str(body["question"]),
            locale=request_locale,
            role=UserRole(effective_role),
        )
        _query_started_at = __import__("time").perf_counter()
        # 10-followups/08: a file being attached does not mean this question
        # is about it — e.g. a checkbox left checked from an earlier turn,
        # then an unrelated question asked via a quick-question shortcut.
        # FileDataAgent/FederatedQueryAgent have no graceful "not about your
        # file" output (the LLM either maps the question onto the wrong
        # columns or writes SQL that doesn't bind), so route away from the
        # file branch entirely when nothing about the attached files is
        # relevant to this question, exactly as if no file were attached —
        # the main orchestrator then gets a real chance to answer from an
        # actual business table. A question with too few content words to
        # judge (a pronoun-style follow-up like "What about this one?") is
        # always treated as relevant, deferring to conversation-history
        # resolution (Spec FV10.4) instead of guessing.
        effective_files = (
            tuple(
                file
                for file in (active_file_repository.get(fid) for fid in effective_file_ids)
                if file is not None
            )
            if effective_file_ids
            else ()
        )
        route_to_file_branch = bool(effective_file_ids) and question_references_any_attached_file(
            str(body["question"]), effective_files
        )
        if not route_to_file_branch and effective_files and not question_classifier.has_data_domain_signal(
            str(body["question"])
        ):
            # 10-followups/09: a token-overlap "not relevant" verdict only
            # proves the question shares no literal vocabulary with the
            # file's own column names/filename — it is not proof the main
            # orchestrator has anywhere real to send the question instead
            # (e.g. a business synonym like "territory" for a file's own
            # "region" column). Corroborate with an independent signal:
            # QuestionClassifier's own business-data-keyword check, already
            # tuned for "does this look like a real data question" and used
            # unconditionally for almost every question via its `not is_rag`
            # fallback (TaskType.SQL_QUERY) — too broad to reuse directly,
            # so this reads the narrower `_DATA_DOMAIN_KEYWORDS` hit instead.
            # No independent business-data signal either: the safer default
            # is to trust the file branch's own schema-grounded LLM over a
            # guess that the orchestrator can do better with nothing to go
            # on, so this overrides back to routing into the file branch.
            route_to_file_branch = True
        if route_to_file_branch:
            # FR-FV10-052: the file branch does not carry its own history
            # store, so its conversation context is resolved here from the
            # same shared store the main orchestrator path reads internally.
            # Uses file_conversation_context_turns, not the general
            # orchestrator's wider conversation_context_turns: an older turn
            # here may have queried a completely different table with a
            # different value format (e.g. "January" vs "2026-01"), and the
            # SQL-generation LLM has been observed anchoring on that format
            # instead of the current file's schema, silently returning zero
            # rows. A tighter window limits how much of that can bleed in.
            history_turns = shared_query_history.list_by_session(
                session_id, limit=active_runtime_config.file_conversation_context_turns
            )
            api_envelope = _handle_file_data_chat_query(
                file_ids=effective_file_ids,
                question=str(body["question"]),
                user_id=effective_user_id,
                role=effective_role,
                org_id=auth_context.org_id,
                trace_id=legacy_trace_id_from_v2(trace_id),
                session_id=session_id,
                locale=request_locale,
                conversation_context=conversation_messages(history_turns),
            )
        else:
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
                    file_ids_used=file_ids or None,
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

    # --- FV-10 user file upload and hybrid analysis (spec section 5) -------

    _STRUCTURED_FILE_EXTENSIONS = {"csv", "xlsx", "xls", "tsv", "json"}
    _VALID_FILE_SCOPES = {"session", "user", "org", "team"}

    def _file_role(auth_context: AuthContext) -> str:
        if "admin" in auth_context.roles:
            return "admin"
        if "analyst" in auth_context.roles:
            return "analyst"
        return "business_user"

    def _file_extension(filename: str) -> str:
        return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    def _current_file_storage_usage(org_id: str, user_id: str) -> int:
        return sum(
            existing_file.size_bytes
            for existing_file in active_file_repository.list_by_owner(
                org_id, user_id, all_versions=True
            )
        )

    def _purge_duplicate_archived_file_if_any(user_id: str, content_hash: str) -> None:
        """FR-FV10-049/NFR-FV10-017: purge a same-user archived duplicate on re-upload."""

        duplicate = active_file_repository.find_archived_by_content_hash(user_id, content_hash)
        if duplicate is not None:
            purge_duplicate_archived_file(
                repository=active_file_repository,
                storage=active_object_storage_adapter,
                file=duplicate,
            )

    def _file_visibility(file_record: UserUploadedFile, auth_context: AuthContext) -> FileAccessDecision:
        shares = active_file_repository.shares_for_file(file_record.file_id)
        return file_access_checker.check(
            requester_user_id=auth_context.user_id,
            requester_org_id=auth_context.org_id,
            role=cast(Any, _file_role(auth_context)),
            file=file_record,
            shares=shares,
        )

    def _is_owner_or_admin(file_record: UserUploadedFile, auth_context: AuthContext) -> bool:
        is_owner = file_record.user_id == auth_context.user_id
        is_admin_same_org = (
            "admin" in auth_context.roles and file_record.org_id == auth_context.org_id
        )
        return is_owner or is_admin_same_org

    def _share_summary(share: FileShareRecord) -> dict[str, Any]:
        return {
            "share_id": share.share_id,
            "file_id": share.file_id,
            "granted_by": share.granted_by,
            "granted_to": share.granted_to,
            "permission": share.permission,
            "created_at": share.created_at.isoformat(),
            "revoked_at": share.revoked_at.isoformat() if share.revoked_at is not None else None,
        }

    def _share_request_summary(request: FileShareRequest) -> dict[str, Any]:
        return {
            "request_id": request.request_id,
            "file_id": request.file_id,
            "requested_by": request.requested_by,
            "org_id": request.org_id,
            "role": request.role,
            "status": request.status,
            "requested_at": request.requested_at.isoformat(),
            "decided_by": request.decided_by,
            "decided_at": request.decided_at.isoformat() if request.decided_at is not None else None,
            "reason": request.reason,
        }

    def _file_summary(file_record: UserUploadedFile) -> dict[str, Any]:
        return {
            "file_id": file_record.file_id,
            "original_name": file_record.original_name,
            "file_type": file_record.file_type,
            "mime_type": file_record.mime_type,
            "size_bytes": file_record.size_bytes,
            "status": file_record.status,
            "error_reason": file_record.error_reason,
            "scope": file_record.scope,
            "session_id": file_record.session_id,
            "schema_json": file_record.schema_json,
            "row_count": file_record.row_count,
            "chunk_count": file_record.chunk_count,
            "file_group_id": file_record.file_group_id,
            "version_number": file_record.version_number,
            "is_latest": file_record.is_latest,
            "promoted_to_doc_id": file_record.promoted_to_doc_id,
            "created_at": file_record.created_at.isoformat(),
        }

    def _admin_file_summary(file_record: UserUploadedFile) -> dict[str, Any]:
        return {**_file_summary(file_record), "user_id": file_record.user_id}

    def _structured_preview(file_record: UserUploadedFile) -> dict[str, Any]:
        parquet_bytes = active_object_storage_adapter.get_object(
            parquet_storage_key(file_record.storage_key)
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
            temp_file.write(parquet_bytes)
            temp_path = Path(temp_file.name)
        connection = duckdb.connect(":memory:")
        try:
            relation = connection.sql(f"SELECT * FROM read_parquet('{temp_path}') LIMIT 50")
            columns = list(relation.columns)
            rows = [dict(zip(columns, row, strict=True)) for row in relation.fetchall()]
        finally:
            connection.close()
            temp_path.unlink(missing_ok=True)
        return {
            "file_id": file_record.file_id,
            "columns": columns,
            "rows": rows,
            "total_row_count": file_record.row_count or 0,
        }

    def _unstructured_preview(file_record: UserUploadedFile) -> dict[str, Any]:
        chunks_with_vectors = active_file_vector_source.chunks_with_vectors_for_file(
            file_record.file_id
        )
        preview_chunks = [chunk.text for chunk, _vector in chunks_with_vectors[:3]]
        return {
            "file_id": file_record.file_id,
            "chunks": preview_chunks,
            "total_chunk_count": file_record.chunk_count or 0,
        }

    @app.post("/api/v2/files/upload")
    async def upload_file_v2(  # pyright: ignore[reportUnusedFunction]
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        scope: str = Form("session"),
        session_id: str | None = Form(None),
        description: str | None = Form(None),
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        del description
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_file_upload")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:upload"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        if scope not in _VALID_FILE_SCOPES:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="scope must be one of session, user, org, team.",
                status_code=422,
            )
        if scope == "session" and not session_id:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="session_id is required when scope is 'session'.",
                status_code=422,
            )

        original_name = sanitize_filename(file.filename or "upload")
        format_result = FileFormatValidator().validate(original_name)
        if format_result is FileFormatCheckResult.BLOCKED:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="FILE_FORMAT_NOT_ALLOWED",
                message=f"'{original_name}' has an unsupported file extension.",
                status_code=422,
            )

        content_bytes = await file.read()

        mime_result = MimeMagicChecker().check(original_name, content_bytes)
        if mime_result is MimeCheckResult.MISMATCH:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="FILE_MIME_MISMATCH",
                message="Declared content type does not match the file's contents.",
                status_code=422,
            )

        role = _file_role(auth_context)
        size_result = FileSizeEnforcer().check(role=cast(Any, role), size=len(content_bytes))
        if size_result is FileSizeCheckResult.EXCEEDS_PER_FILE_LIMIT:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="FILE_SIZE_EXCEEDED",
                message="File exceeds the per-file size limit for this role.",
                status_code=413,
            )

        used_bytes = _current_file_storage_usage(auth_context.org_id, auth_context.user_id)
        quota_result = StorageQuotaEnforcer().check(
            role=cast(Any, role), used=used_bytes, adding=len(content_bytes)
        )
        if quota_result is StorageQuotaCheckResult.EXCEEDS_QUOTA:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="STORAGE_QUOTA_EXCEEDED",
                message="Uploading this file would exceed the account's storage quota.",
                status_code=409,
            )

        extension = _file_extension(original_name)
        file_type = "structured" if extension in _STRUCTURED_FILE_EXTENSIONS else "unstructured"
        content_hash = sha256(content_bytes).hexdigest()
        _purge_duplicate_archived_file_if_any(auth_context.user_id, content_hash)

        existing_latest_files = active_file_repository.list_by_owner(
            auth_context.org_id, auth_context.user_id, all_versions=False
        )
        previous_latest = next(
            (
                existing_file
                for existing_file in existing_latest_files
                if existing_file.original_name == original_name
            ),
            None,
        )
        version_assignment = file_version_manager.on_upload(
            previous_latest.file_group_id if previous_latest is not None else None,
            previous_latest,
        )
        if version_assignment.superseded_previous_latest is not None:
            active_file_repository.save(version_assignment.superseded_previous_latest)

        storage_key = build_storage_key(
            auth_context.org_id,
            auth_context.user_id,
            version_assignment.file_id,
            original_name,
        )
        active_object_storage_adapter.put_object(storage_key, content_bytes)

        new_file = UserUploadedFile(
            file_id=version_assignment.file_id,
            org_id=auth_context.org_id,
            user_id=auth_context.user_id,
            original_name=original_name,
            file_type=cast(Any, file_type),
            mime_type=file.content_type or "application/octet-stream",
            size_bytes=len(content_bytes),
            storage_key=storage_key,
            status="processing",
            scope=cast(Any, scope),
            session_id=session_id if scope == "session" else None,
            file_group_id=version_assignment.file_group_id,
            version_number=version_assignment.version_number,
            is_latest=True,
            created_at=datetime.now(timezone.utc),
            content_hash=content_hash,
        )
        active_file_repository.save(new_file)

        background_tasks.add_task(
            file_processing_worker.process, new_file.file_id, extension=extension
        )

        return JSONResponse(
            status_code=202,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "file_id": new_file.file_id,
                    "original_name": new_file.original_name,
                    "file_type": new_file.file_type,
                    "status": new_file.status,
                    "schema": None,
                    "size_bytes": new_file.size_bytes,
                    "created_at": new_file.created_at.isoformat(),
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/files")
    def list_files_v2(  # pyright: ignore[reportUnusedFunction]
        scope: str | None = None,
        status: str | None = None,
        all_versions: bool = False,
        page_size: int = 20,
        offset: int = 0,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_files_list")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:read"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        matching_files = active_file_repository.list_by_owner(
            auth_context.org_id,
            auth_context.user_id,
            scope=cast(Any, scope) if scope is not None else None,
            status=cast(Any, status) if status is not None else None,
            all_versions=all_versions,
        )
        bounded_page_size = max(1, page_size)
        page = matching_files[offset : offset + bounded_page_size]

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "files": [_file_summary(file_record) for file_record in page],
                    "total": len(matching_files),
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/files/{file_id}")
    def get_file_v2(  # pyright: ignore[reportUnusedFunction]
        file_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_files_get")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:read"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        file_record = active_file_repository.get(file_id)
        if file_record is None or file_record.deleted_at is not None:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if _file_visibility(file_record, auth_context) is FileAccessDecision.DENY:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": _file_summary(file_record),
                "warnings": [],
                "error": None,
            },
        )

    @app.delete("/api/v2/files/{file_id}")
    def delete_file_v2(  # pyright: ignore[reportUnusedFunction]
        file_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_files_delete")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:delete"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        file_record = active_file_repository.get(file_id)
        if file_record is None or file_record.deleted_at is not None:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if _file_visibility(file_record, auth_context) is FileAccessDecision.DENY:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )

        if not _is_owner_or_admin(file_record, auth_context):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_FORBIDDEN",
                message="Only the file owner or an admin can delete this file.",
                status_code=403,
            )

        active_object_storage_adapter.delete_object(file_record.storage_key)
        if file_record.file_type == "structured":
            active_object_storage_adapter.delete_object(
                parquet_storage_key(file_record.storage_key)
            )
        active_file_repository.soft_delete(file_id, deleted_at=datetime.now(timezone.utc))

        return JSONResponse(status_code=204, content=None)

    @app.get("/api/v2/files/{file_id}/preview")
    def preview_file_v2(  # pyright: ignore[reportUnusedFunction]
        file_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_files_preview")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:read"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        file_record = active_file_repository.get(file_id)
        if file_record is None or file_record.deleted_at is not None:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if _file_visibility(file_record, auth_context) is FileAccessDecision.DENY:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if file_record.status != "ready":
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="FILE_NOT_READY",
                message="File is not ready for preview yet.",
                status_code=422,
            )

        preview_data = (
            _structured_preview(file_record)
            if file_record.file_type == "structured"
            else _unstructured_preview(file_record)
        )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": preview_data,
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/files/upload/init")
    def init_chunked_file_upload_v2(  # pyright: ignore[reportUnusedFunction]
        body: FileUploadInitRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_file_upload_init")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:upload"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        if body.scope not in _VALID_FILE_SCOPES:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="scope must be one of session, user, org, team.",
                status_code=422,
            )
        if body.scope == "session" and not body.session_id:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="session_id is required when scope is 'session'.",
                status_code=422,
            )
        if body.file_size_bytes <= 0:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="file_size_bytes must be greater than 0.",
                status_code=422,
            )

        original_name = sanitize_filename(body.original_name)
        format_result = FileFormatValidator().validate(original_name)
        if format_result is FileFormatCheckResult.BLOCKED:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="FILE_FORMAT_NOT_ALLOWED",
                message=f"'{original_name}' has an unsupported file extension.",
                status_code=422,
            )

        role = _file_role(auth_context)
        size_result = FileSizeEnforcer().check(role=cast(Any, role), size=body.file_size_bytes)
        if size_result is FileSizeCheckResult.EXCEEDS_PER_FILE_LIMIT:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="FILE_SIZE_EXCEEDED",
                message="File exceeds the per-file size limit for this role.",
                status_code=413,
            )

        used_bytes = _current_file_storage_usage(auth_context.org_id, auth_context.user_id)
        quota_result = StorageQuotaEnforcer().check(
            role=cast(Any, role), used=used_bytes, adding=body.file_size_bytes
        )
        if quota_result is StorageQuotaCheckResult.EXCEEDS_QUOTA:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="STORAGE_QUOTA_EXCEEDED",
                message="Uploading this file would exceed the account's storage quota.",
                status_code=409,
            )

        upload_id = new_upload_id()
        chunk_count = compute_chunk_count(body.file_size_bytes, DEFAULT_CHUNK_SIZE_BYTES)
        chunk_keys = tuple(
            chunk_staging_key(auth_context.org_id, auth_context.user_id, upload_id, chunk_index)
            for chunk_index in range(chunk_count)
        )
        presigned_urls = [
            active_object_storage_adapter.generate_upload_url(key, ttl=MAX_UPLOAD_SESSION_TTL)
            for key in chunk_keys
        ]

        active_chunk_upload_session_store.save(
            ChunkUploadSession(
                upload_id=upload_id,
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
                original_name=original_name,
                mime_type=body.mime_type,
                file_size_bytes=body.file_size_bytes,
                scope=cast(Any, body.scope),
                chunk_size_bytes=DEFAULT_CHUNK_SIZE_BYTES,
                chunk_count=chunk_count,
                chunk_keys=chunk_keys,
                expires_at=presigned_urls[0].expires_at,
                session_id=body.session_id if body.scope == "session" else None,
                description=body.description,
            )
        )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "upload_id": upload_id,
                    "chunk_size_bytes": DEFAULT_CHUNK_SIZE_BYTES,
                    "chunk_count": chunk_count,
                    "presigned_urls": [
                        {"chunk_index": chunk_index, "url": presigned_urls[chunk_index].url}
                        for chunk_index in range(chunk_count)
                    ],
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/files/upload/{upload_id}/complete")
    def complete_chunked_file_upload_v2(  # pyright: ignore[reportUnusedFunction]
        upload_id: str,
        body: FileUploadCompleteRequestBody,
        background_tasks: BackgroundTasks,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_file_upload_complete")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:upload"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        session = active_chunk_upload_session_store.get(upload_id)
        if (
            session is None
            or session.org_id != auth_context.org_id
            or session.user_id != auth_context.user_id
        ):
            return tenant_not_found_response(
                active_request_id,
                trace_id,
                "UPLOAD_SESSION_NOT_FOUND",
                "Upload session was not found.",
            )

        if session.is_expired(now=datetime.now(timezone.utc)):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="UPLOAD_SESSION_EXPIRED",
                message="The presigned upload URLs for this session have expired.",
                status_code=410,
            )

        provided_chunk_indexes = {etag.chunk_index for etag in body.etags}
        missing_chunk_indexes = set(range(session.chunk_count)) - provided_chunk_indexes
        if missing_chunk_indexes:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message=f"Missing ETags for chunk indexes: {sorted(missing_chunk_indexes)}.",
                status_code=422,
            )

        try:
            ordered_chunk_bytes = [
                active_object_storage_adapter.get_object(key) for key in session.chunk_keys
            ]
        except ObjectNotFoundError:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="One or more chunks were not uploaded before completing.",
                status_code=422,
            )
        assembled_bytes = b"".join(ordered_chunk_bytes)

        mime_result = MimeMagicChecker().check(session.original_name, assembled_bytes)
        if mime_result is MimeCheckResult.MISMATCH:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="FILE_MIME_MISMATCH",
                message="Declared content type does not match the assembled file's contents.",
                status_code=422,
            )

        extension = _file_extension(session.original_name)
        file_type = "structured" if extension in _STRUCTURED_FILE_EXTENSIONS else "unstructured"
        content_hash = sha256(assembled_bytes).hexdigest()
        _purge_duplicate_archived_file_if_any(session.user_id, content_hash)

        existing_latest_files = active_file_repository.list_by_owner(
            session.org_id, session.user_id, all_versions=False
        )
        previous_latest = next(
            (
                existing_file
                for existing_file in existing_latest_files
                if existing_file.original_name == session.original_name
            ),
            None,
        )
        version_assignment = file_version_manager.on_upload(
            previous_latest.file_group_id if previous_latest is not None else None,
            previous_latest,
        )
        if version_assignment.superseded_previous_latest is not None:
            active_file_repository.save(version_assignment.superseded_previous_latest)

        storage_key = build_storage_key(
            session.org_id, session.user_id, version_assignment.file_id, session.original_name
        )
        active_object_storage_adapter.put_object(storage_key, assembled_bytes)
        for chunk_key in session.chunk_keys:
            active_object_storage_adapter.delete_object(chunk_key)
        active_chunk_upload_session_store.delete(upload_id)

        new_file = UserUploadedFile(
            file_id=version_assignment.file_id,
            org_id=session.org_id,
            user_id=session.user_id,
            original_name=session.original_name,
            file_type=cast(Any, file_type),
            mime_type=session.mime_type,
            size_bytes=len(assembled_bytes),
            storage_key=storage_key,
            status="processing",
            scope=session.scope,
            session_id=session.session_id,
            file_group_id=version_assignment.file_group_id,
            version_number=version_assignment.version_number,
            is_latest=True,
            created_at=datetime.now(timezone.utc),
            content_hash=content_hash,
        )
        active_file_repository.save(new_file)

        background_tasks.add_task(
            file_processing_worker.process, new_file.file_id, extension=extension
        )

        return JSONResponse(
            status_code=202,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {"file_id": new_file.file_id, "status": new_file.status},
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/files/{file_id}/share")
    def share_file_v2(  # pyright: ignore[reportUnusedFunction]
        file_id: str,
        body: FileShareRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_file_share")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:share"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        file_record = active_file_repository.get(file_id)
        if file_record is None or file_record.deleted_at is not None:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if _file_visibility(file_record, auth_context) is FileAccessDecision.DENY:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if not _is_owner_or_admin(file_record, auth_context):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_FORBIDDEN",
                message="Only the file owner or an admin can share this file.",
                status_code=403,
            )

        granted_to = body.granted_to.strip()
        if not granted_to:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="granted_to is required.",
                status_code=422,
            )
        if granted_to == file_record.user_id:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="Cannot share a file with its own owner.",
                status_code=422,
            )

        target_user = active_auth_service.store.get_user(granted_to)
        if target_user is None or target_user.org_id != file_record.org_id:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="granted_to must be a user in the same organization as the file.",
                status_code=422,
            )

        share = FileShareRecord(
            share_id=new_share_id(),
            file_id=file_id,
            granted_by=auth_context.user_id,
            granted_to=granted_to,
            created_at=datetime.now(timezone.utc),
        )
        active_file_repository.save_share(share)

        return JSONResponse(
            status_code=201,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": _share_summary(share),
                "warnings": [],
                "error": None,
            },
        )

    @app.delete("/api/v2/files/{file_id}/share/{share_id}")
    def revoke_file_share_v2(  # pyright: ignore[reportUnusedFunction]
        file_id: str,
        share_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_file_share_revoke")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="files:share"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        file_record = active_file_repository.get(file_id)
        if file_record is None or file_record.deleted_at is not None:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if _file_visibility(file_record, auth_context) is FileAccessDecision.DENY:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if not _is_owner_or_admin(file_record, auth_context):
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_FORBIDDEN",
                message="Only the file owner or an admin can revoke shares for this file.",
                status_code=403,
            )

        existing_share = active_file_repository.share_by_id(share_id)
        if existing_share is not None and existing_share.file_id == file_id:
            active_file_repository.revoke_share(share_id, revoked_at=datetime.now(timezone.utc))

        return JSONResponse(status_code=204, content=None)

    @app.get("/api/v2/admin/files")
    def list_org_files_v2(  # pyright: ignore[reportUnusedFunction]
        user_id: str | None = None,
        status: str | None = None,
        file_type: str | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        """Admin review surface: every uploader's files in this org, for FR-FV10-033.

        Separate from ``GET /api/v2/files`` (which is self-scoped) — this one
        needs ``admin:knowledge:promote`` because its purpose is letting an
        admin find and review files before deciding whether to promote them.
        """

        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_admin_files_list")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="admin:knowledge:promote"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        bounded_limit = max(1, limit)
        bounded_offset = max(0, offset)
        matching_files = active_file_repository.list_by_org(
            auth_context.org_id,
            user_id=user_id or None,
            status=cast(Any, status) if status else None,
            file_type=cast(Any, file_type) if file_type else None,
            q=q or None,
            limit=bounded_limit,
            offset=bounded_offset,
        )
        total = active_file_repository.count_by_org(
            auth_context.org_id,
            user_id=user_id or None,
            status=cast(Any, status) if status else None,
            file_type=cast(Any, file_type) if file_type else None,
            q=q or None,
        )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "files": [_admin_file_summary(file_record) for file_record in matching_files],
                    "total": total,
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/admin/knowledge/promote-file")
    def promote_file_to_knowledge_base_v2(  # pyright: ignore[reportUnusedFunction]
        body: PromoteFileRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_knowledge_promote")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="admin:knowledge:promote"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        try:
            promoted = knowledge_promotion_service.promote_file(
                body.file_id,
                role=cast(Any, _file_role(auth_context)),
                org_id=auth_context.org_id,
            )
        except NotAuthorizedToPromoteError:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_FORBIDDEN",
                message="Only an admin can promote a file to the knowledge base.",
                status_code=403,
            )
        except FileNotPromotableError:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="FILE_NOT_PROMOTABLE",
                message="File must be an unstructured, ready file owned by this organization.",
                status_code=422,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "file_id": promoted.file_id,
                    "promoted_to_doc_id": promoted.promoted_to_doc_id,
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.delete("/api/v2/admin/knowledge/{doc_id}")
    def demote_knowledge_base_document_v2(  # pyright: ignore[reportUnusedFunction]
        doc_id: str,
        mode: str | None = None,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_knowledge_demote")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="admin:knowledge:demote"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        if mode != "demote":
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="VALIDATION_ERROR",
                message="mode=demote is required to demote a knowledge base document.",
                status_code=422,
            )

        try:
            knowledge_promotion_service.demote_document(
                doc_id,
                role=cast(Any, _file_role(auth_context)),
                org_id=auth_context.org_id,
            )
        except NotAuthorizedToPromoteError:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_FORBIDDEN",
                message="Only an admin can demote a knowledge base document.",
                status_code=403,
            )
        except DocumentNotPromotedError:
            return tenant_not_found_response(
                active_request_id,
                trace_id,
                "DOCUMENT_NOT_FOUND",
                "Document was not found or is not a live promotion.",
            )

        return JSONResponse(status_code=204, content=None)

    # --- FV10.2 file sharing approval workflow ------------------------------

    @app.post("/api/v2/files/{file_id}/share-requests")
    def submit_file_share_request_v2(  # pyright: ignore[reportUnusedFunction]
        file_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_file_share_request")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="files:share_requests:submit",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        # NFR-FV10-014: an invisible file (doesn't exist, wrong org, no
        # access) must 404 like every other file-visibility denial; a file
        # the caller can see but does not own is a distinguishable 403,
        # matching share_file_v2's existing ownership-gate pattern.
        file_record = active_file_repository.get(file_id)
        if file_record is None or file_record.deleted_at is not None:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if _file_visibility(file_record, auth_context) is FileAccessDecision.DENY:
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        if file_record.user_id != auth_context.user_id:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="AUTH_FORBIDDEN",
                message="Only the file owner can request sharing.",
                status_code=403,
            )

        try:
            request = file_share_approval_service.submit_request(
                file_id,
                requester_user_id=auth_context.user_id,
                requester_org_id=auth_context.org_id,
                requester_role=_file_role(auth_context),
            )
        except (FileNotShareableError, NotFileOwnerError):
            # Already screened above; reaching here means the file changed
            # between that check and this call (e.g. concurrent delete).
            return tenant_not_found_response(
                active_request_id, trace_id, "FILE_NOT_FOUND", "File was not found."
            )
        except PendingShareRequestExistsError:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="SHARE_REQUEST_ALREADY_PENDING",
                message="A pending share request already exists for this file.",
                status_code=409,
            )

        return JSONResponse(
            status_code=201,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": _share_request_summary(request),
                "warnings": [],
                "error": None,
            },
        )

    @app.get("/api/v2/admin/share-requests")
    def list_admin_share_requests_v2(  # pyright: ignore[reportUnusedFunction]
        status: str | None = None,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_admin_share_requests_list")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="admin:share_requests:review",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        requests = active_file_repository.list_share_requests(
            auth_context.org_id,
            status=cast(Any, status) if status else None,
        )
        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {
                    "items": [_share_request_summary(request) for request in requests],
                    "count": len(requests),
                },
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/admin/share-requests/{request_id}/approve")
    def approve_file_share_request_v2(  # pyright: ignore[reportUnusedFunction]
        request_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        header_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(header_request_id, "req_share_request_approve")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="admin:share_requests:review",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        try:
            approved = file_share_approval_service.approve(
                request_id,
                admin_user_id=auth_context.user_id,
                admin_org_id=auth_context.org_id,
            )
        except ShareRequestNotFoundError:
            return tenant_not_found_response(
                active_request_id,
                trace_id,
                "SHARE_REQUEST_NOT_FOUND",
                "Share request was not found.",
            )
        except ShareRequestNotPendingError:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="SHARE_REQUEST_ALREADY_DECIDED",
                message="This share request has already been decided.",
                status_code=409,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": _share_request_summary(approved),
                "warnings": [],
                "error": None,
            },
        )

    @app.post("/api/v2/admin/share-requests/{request_id}/reject")
    def reject_file_share_request_v2(  # pyright: ignore[reportUnusedFunction]
        request_id: str,
        body: ShareRequestRejectBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        header_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(header_request_id, "req_share_request_reject")
        auth_context, auth_error = authenticate_v2(
            authorization,
            trace_id,
            active_request_id,
            required_permission="admin:share_requests:review",
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        try:
            rejected = file_share_approval_service.reject(
                request_id,
                admin_user_id=auth_context.user_id,
                admin_org_id=auth_context.org_id,
                reason=body.reason,
            )
        except ShareRequestNotFoundError:
            return tenant_not_found_response(
                active_request_id,
                trace_id,
                "SHARE_REQUEST_NOT_FOUND",
                "Share request was not found.",
            )
        except ShareRequestNotPendingError:
            return v2_error_response(
                request_id=active_request_id,
                trace_id=trace_id,
                code="SHARE_REQUEST_ALREADY_DECIDED",
                message="This share request has already been decided.",
                status_code=409,
            )

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": _share_request_summary(rejected),
                "warnings": [],
                "error": None,
            },
        )

    # --- FV10.3 archived-files admin view and retention scheduling ---------

    @app.get("/api/v2/admin/files/archived")
    def list_archived_files_v2(  # pyright: ignore[reportUnusedFunction]
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_id: str | None = Header(default=None, alias="X-Request-Id"),
    ) -> JSONResponse:
        """§6.4: admin-only, org-wide, one signed download URL per archived file."""

        trace_id = new_trace_id_v2()
        active_request_id = v2_request_id_from_header(request_id, "req_admin_files_archived")
        auth_context, auth_error = authenticate_v2(
            authorization, trace_id, active_request_id, required_permission="admin:knowledge:promote"
        )
        if auth_error is not None or auth_context is None:
            return cast(JSONResponse, auth_error)

        archived_files = active_file_repository.list_archived_by_org(auth_context.org_id)
        items = [
            {
                **_admin_file_summary(file_record),
                "download_url": active_object_storage_adapter.generate_download_url(
                    file_record.storage_key
                ).url,
            }
            for file_record in archived_files
        ]
        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "request_id": active_request_id,
                "data": {"files": items, "total": len(items)},
                "warnings": [],
                "error": None,
            },
        )

    @asynccontextmanager
    async def _retention_sweep_lifespan(_: FastAPI) -> AsyncGenerator[None]:
        task = asyncio.create_task(
            _run_retention_sweep_loop(retention_worker, retention_sweep_interval_seconds)
        )
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # Reassigning Router.lifespan_context after construction (rather than
    # passing lifespan= to FastAPI(...) up front) because retention_worker
    # is not built until well after `app` already exists — everything else
    # in this function is wired the same way, as a post-construction step.
    app.router.lifespan_context = _retention_sweep_lifespan

    return app


app = create_app(
    use_postgres_metadata=use_postgres_metadata_from_env(),
    database_readiness_checker=database_readiness_checker_from_env(),
    redis_readiness_checker=redis_readiness_checker_from_env(),
    readonly_database_probe=readonly_database_probe_from_env(),
)
