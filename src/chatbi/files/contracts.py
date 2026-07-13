"""Typed data contracts for the user file upload and hybrid analysis feature.

These models follow
``spec/final-version/en/10-user-file-upload-and-hybrid-analysis.spec.md``
section 6. They describe the shape of every record and request/response
payload before storage, parsing, agent, and API code moves data around.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

from chatbi.core.architecture_contracts import UserRoleV2
from chatbi.core.contracts import EvidenceItem, TableResult


FileType = Literal["structured", "unstructured"]
FileStatus = Literal["processing", "schema_ready", "indexing", "ready", "failed"]
FileScope = Literal["session", "user", "org", "team"]
SharePermission = Literal["read"]
ResultSourceType = Literal["file", "database", "federated"]
FileShareRequestStatus = Literal["pending", "approved", "rejected"]


def _require_non_empty(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_prefix(field_name: str, value: str, prefix: str) -> None:
    _require_non_empty(field_name, value)
    if not value.startswith(prefix):
        raise ValueError(f"{field_name} must start with '{prefix}'")


@dataclass(frozen=True, slots=True)
class UserUploadedFile:
    """A single stored file record. See spec section 6.1."""

    file_id: str
    org_id: str
    user_id: str
    original_name: str
    file_type: FileType
    mime_type: str
    size_bytes: int
    storage_key: str
    status: FileStatus
    scope: FileScope
    file_group_id: str
    version_number: int
    is_latest: bool
    created_at: datetime
    content_hash: str
    schema_json: Mapping[str, Any] | None = None
    row_count: int | None = None
    chunk_count: int | None = None
    error_reason: str | None = None
    session_id: str | None = None
    promoted_to_doc_id: str | None = None
    last_accessed_at: datetime | None = None
    expires_at: datetime | None = None
    deleted_at: datetime | None = None
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_prefix("file_id", self.file_id, "ufile_")
        _require_non_empty("org_id", self.org_id)
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("original_name", self.original_name)
        _require_non_empty("mime_type", self.mime_type)
        _require_non_empty("storage_key", self.storage_key)
        _require_non_empty("file_group_id", self.file_group_id)
        _require_non_empty("content_hash", self.content_hash)
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be greater than or equal to 0")
        if self.version_number < 1:
            raise ValueError("version_number must be greater than or equal to 1")
        if self.scope == "session" and not self.session_id:
            raise ValueError("session_id is required when scope is 'session'")
        if self.file_type == "unstructured":
            if self.schema_json is not None:
                raise ValueError("schema_json must be None for unstructured files")
            if self.row_count is not None:
                raise ValueError("row_count must be None for unstructured files")
        if self.file_type == "structured":
            if self.chunk_count is not None:
                raise ValueError("chunk_count must be None for structured files")
            if self.status == "ready" and self.schema_json is None:
                raise ValueError("schema_json is required once a structured file is ready")
            if self.status == "ready" and self.row_count is None:
                raise ValueError("row_count is required once a structured file is ready")
        if self.status == "failed" and not self.error_reason:
            raise ValueError("error_reason is required when status is 'failed'")


@dataclass(frozen=True, slots=True)
class FileUploadInitRequest:
    """Chunked-upload initiation request. See spec section 6.2."""

    original_name: str
    file_size_bytes: int
    mime_type: str
    scope: FileScope
    session_id: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("original_name", self.original_name)
        _require_non_empty("mime_type", self.mime_type)
        if self.file_size_bytes <= 0:
            raise ValueError("file_size_bytes must be greater than 0")
        if self.scope == "session" and not self.session_id:
            raise ValueError("session_id is required when scope is 'session'")


@dataclass(frozen=True, slots=True)
class ChunkUrl:
    chunk_index: int
    url: str

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be greater than or equal to 0")
        _require_non_empty("url", self.url)


@dataclass(frozen=True, slots=True)
class FileUploadInitResponse:
    """Chunked-upload initiation response. See spec section 6.3."""

    upload_id: str
    chunk_size_bytes: int
    chunk_count: int
    presigned_urls: tuple[ChunkUrl, ...]

    def __post_init__(self) -> None:
        _require_prefix("upload_id", self.upload_id, "upl_")
        if self.chunk_size_bytes <= 0:
            raise ValueError("chunk_size_bytes must be greater than 0")
        if self.chunk_count < 1:
            raise ValueError("chunk_count must be greater than or equal to 1")
        if len(self.presigned_urls) != self.chunk_count:
            raise ValueError("presigned_urls must contain exactly chunk_count entries")


@dataclass(frozen=True, slots=True)
class ChunkEtag:
    chunk_index: int
    etag: str

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be greater than or equal to 0")
        _require_non_empty("etag", self.etag)


@dataclass(frozen=True, slots=True)
class FileUploadCompleteRequest:
    """Chunked-upload assembly request. See spec section 6.4."""

    etags: tuple[ChunkEtag, ...]

    def __post_init__(self) -> None:
        if not self.etags:
            raise ValueError("etags must contain at least one entry")


@dataclass(frozen=True, slots=True)
class FileShareRecord:
    """A grant of read access to a shared file. See spec section 6.5."""

    share_id: str
    file_id: str
    granted_by: str
    granted_to: str
    created_at: datetime
    permission: SharePermission = "read"
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_prefix("share_id", self.share_id, "shr_")
        _require_prefix("file_id", self.file_id, "ufile_")
        _require_non_empty("granted_by", self.granted_by)
        _require_non_empty("granted_to", self.granted_to)
        if self.granted_by == self.granted_to:
            raise ValueError("granted_by and granted_to must differ")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class FileShareRequest:
    """An analyst-initiated, admin-approved request to widen a file's
    visibility to every colleague sharing the requester's org and role
    (Spec FV10.2). See spec section 6.1.
    """

    request_id: str          # prefix req_share_
    file_id: str
    requested_by: str        # user_id
    org_id: str
    role: str                # requester's role at request time; fan-out target
    status: FileShareRequestStatus
    requested_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_prefix("request_id", self.request_id, "req_share_")
        _require_prefix("file_id", self.file_id, "ufile_")
        _require_non_empty("requested_by", self.requested_by)
        _require_non_empty("org_id", self.org_id)
        _require_non_empty("role", self.role)
        if self.status == "pending":
            if self.decided_by is not None or self.decided_at is not None:
                raise ValueError("a pending request must not have decided_by/decided_at")
        elif self.decided_by is None or self.decided_at is None:
            raise ValueError("decided_by and decided_at are required once a request is decided")


@dataclass(frozen=True, slots=True)
class FilePreviewResponse:
    """Preview payload for structured or unstructured files. See spec 6.6."""

    file_id: str
    columns: tuple[str, ...] | None = None
    rows: tuple[Mapping[str, Any], ...] | None = None
    total_row_count: int | None = None
    chunks: tuple[str, ...] | None = None
    total_chunk_count: int | None = None

    def __post_init__(self) -> None:
        _require_prefix("file_id", self.file_id, "ufile_")
        is_structured = self.columns is not None
        is_unstructured = self.chunks is not None
        if is_structured == is_unstructured:
            raise ValueError(
                "exactly one of (columns, rows, total_row_count) or "
                "(chunks, total_chunk_count) must be set"
            )
        if is_structured:
            if self.rows is None or self.total_row_count is None:
                raise ValueError("rows and total_row_count are required for structured previews")
            if len(self.rows) > 50:
                raise ValueError("rows must contain at most 50 entries")
        else:
            if self.total_chunk_count is None:
                raise ValueError("total_chunk_count is required for unstructured previews")
            assert self.chunks is not None
            if len(self.chunks) > 3:
                raise ValueError("chunks must contain at most 3 entries")


@dataclass(frozen=True, slots=True)
class FileDataAgentInput:
    """Input to ``FileDataAgent``. See spec section 6.7.

    ``user_id`` is not listed explicitly in section 6.7's field list, but
    FR-FV10-018's ownership check (TC-FV10-022) has no other field to compare
    ``file.user_id`` against, so it is required here.
    """

    file_ids: tuple[str, ...]
    user_id: str
    question: str
    role: UserRoleV2
    trace_id: str
    conversation_context: tuple[Mapping[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.file_ids:
            raise ValueError("file_ids must not be empty")
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("question", self.question)
        _require_non_empty("trace_id", self.trace_id)


@dataclass(frozen=True, slots=True)
class FileDataAgentOutput:
    """Output from ``FileDataAgent``. See spec section 6.8."""

    file_ids_queried: tuple[str, ...]
    guardrail_blocked: bool
    table_result: TableResult | None = None
    error_code: str | None = None
    duckdb_sql: str | None = None

    def __post_init__(self) -> None:
        if self.guardrail_blocked and self.table_result is not None:
            raise ValueError("a guardrail-blocked output must not include a table_result")


@dataclass(frozen=True, slots=True)
class PostgresQueryContext:
    """Materialization bounds for the Postgres side of a federated query."""

    table_name: str
    columns: tuple[str, ...]
    max_rows: int

    def __post_init__(self) -> None:
        _require_non_empty("table_name", self.table_name)
        if not self.columns:
            raise ValueError("columns must not be empty")
        if self.max_rows <= 0:
            raise ValueError("max_rows must be greater than 0")


@dataclass(frozen=True, slots=True)
class FederatedQueryAgentInput:
    """Input to ``FederatedQueryAgent``. See spec section 6.9.

    ``user_id`` is not listed explicitly in section 6.9's field list, for the
    same reason it was added to ``FileDataAgentInput``: the ownership check
    over ``file_ids`` has no other field to compare ``file.user_id`` against.
    """

    file_ids: tuple[str, ...]
    user_id: str
    pg_context: PostgresQueryContext
    question: str
    role: UserRoleV2
    trace_id: str
    conversation_context: tuple[Mapping[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.file_ids:
            raise ValueError("file_ids must not be empty")
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("question", self.question)
        _require_non_empty("trace_id", self.trace_id)


@dataclass(frozen=True, slots=True)
class FederatedQueryAgentOutput:
    """Output from ``FederatedQueryAgent``. See spec section 6.10."""

    degraded: bool
    table_result: TableResult | None = None
    degradation_reason: str | None = None
    error_code: str | None = None
    federated_sql: str | None = None
    # 10-followups/12: True only when the query matched zero rows despite a
    # JOIN and non-empty sources — indistinguishable from a real "compared
    # everything, nothing exceeded the threshold" result unless callers are
    # told which case this was. See FederatedQueryAgent._compute_zero_row_join_caveat.
    zero_row_join_caveat: bool = False

    def __post_init__(self) -> None:
        if self.degraded and self.degradation_reason is None:
            raise ValueError("a degraded output must include degradation_reason")
        if not self.degraded and self.degradation_reason is not None:
            raise ValueError("a non-degraded output must not include degradation_reason")


def _empty_evidence() -> tuple[str, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class SourcedTableResult:
    """A ``TableResult`` tagged with its originating data source (FR-FV10-024)."""

    table_result: TableResult
    source: ResultSourceType
    file_ids: tuple[str, ...] = field(default_factory=_empty_evidence)


@dataclass(frozen=True, slots=True)
class SourcedEvidenceItem:
    """An ``EvidenceItem`` tagged with whether it came from a user upload (FR-FV10-025)."""

    evidence: EvidenceItem
    is_uploaded_file: bool = False
