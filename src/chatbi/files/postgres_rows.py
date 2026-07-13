"""PostgreSQL table DDL and row mapping for the user file upload feature.

This module is deliberately database-driver free: it defines the
``user_uploaded_files`` / ``user_file_shares`` DDL from spec section 6.13 and
the conversion between typed contracts and PostgreSQL-shaped rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, cast

from chatbi.files.contracts import (
    FileScope,
    FileShareRecord,
    FileShareRequest,
    FileShareRequestStatus,
    FileStatus,
    FileType,
    SharePermission,
    UserUploadedFile,
)


FILE_UPLOAD_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS user_uploaded_files (
    file_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('structured', 'unstructured')),
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    storage_key TEXT NOT NULL,
    schema_json JSONB,
    row_count INTEGER,
    chunk_count INTEGER,
    status TEXT NOT NULL CHECK (
        status IN ('processing', 'schema_ready', 'indexing', 'ready', 'failed')
    ),
    error_reason TEXT,
    scope TEXT NOT NULL CHECK (scope IN ('session', 'user', 'org', 'team')),
    session_id TEXT,
    file_group_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    is_latest BOOLEAN NOT NULL,
    promoted_to_doc_id TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    last_accessed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    content_hash TEXT,
    archived_at TIMESTAMPTZ
);
ALTER TABLE user_uploaded_files ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE user_uploaded_files ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

UPDATE user_uploaded_files
SET content_hash = encode(sha256(file_id::bytea), 'hex')
WHERE content_hash IS NULL OR content_hash = '';

CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_org_user_created
    ON user_uploaded_files (org_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_session_status
    ON user_uploaded_files (session_id, status) WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_group_version
    ON user_uploaded_files (file_group_id, version_number DESC);

CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_content_hash
    ON user_uploaded_files (user_id, content_hash) WHERE archived_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_file_shares (
    share_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES user_uploaded_files(file_id),
    granted_by TEXT NOT NULL,
    granted_to TEXT NOT NULL,
    permission TEXT NOT NULL CHECK (permission = 'read'),
    created_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_file_shares_file_granted_to_active
    ON user_file_shares (file_id, granted_to) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS file_share_requests (
    request_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES user_uploaded_files(file_id),
    requested_by TEXT NOT NULL,
    org_id TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at TIMESTAMPTZ NOT NULL,
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_file_share_requests_file_status
    ON file_share_requests (file_id, status);

CREATE INDEX IF NOT EXISTS idx_file_share_requests_org_status_requested_at
    ON file_share_requests (org_id, status, requested_at DESC);
""".strip()


def file_to_row(file: UserUploadedFile) -> Mapping[str, object | None]:
    return {
        "file_id": file.file_id,
        "org_id": file.org_id,
        "user_id": file.user_id,
        "original_name": file.original_name,
        "file_type": file.file_type,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "storage_key": file.storage_key,
        "schema_json": file.schema_json,
        "row_count": file.row_count,
        "chunk_count": file.chunk_count,
        "status": file.status,
        "error_reason": file.error_reason,
        "scope": file.scope,
        "session_id": file.session_id,
        "file_group_id": file.file_group_id,
        "version_number": file.version_number,
        "is_latest": file.is_latest,
        "promoted_to_doc_id": file.promoted_to_doc_id,
        "created_at": file.created_at,
        "last_accessed_at": file.last_accessed_at,
        "expires_at": file.expires_at,
        "deleted_at": file.deleted_at,
        "content_hash": file.content_hash,
        "archived_at": file.archived_at,
    }


def file_from_row(row: Mapping[str, object]) -> UserUploadedFile:
    return UserUploadedFile(
        file_id=_string(row, "file_id"),
        org_id=_string(row, "org_id"),
        user_id=_string(row, "user_id"),
        original_name=_string(row, "original_name"),
        file_type=cast(FileType, _string(row, "file_type")),
        mime_type=_string(row, "mime_type"),
        size_bytes=_integer(row, "size_bytes"),
        storage_key=_string(row, "storage_key"),
        status=cast(FileStatus, _string(row, "status")),
        scope=cast(FileScope, _string(row, "scope")),
        file_group_id=_string(row, "file_group_id"),
        version_number=_integer(row, "version_number"),
        is_latest=_bool(row, "is_latest"),
        created_at=_datetime(row, "created_at"),
        content_hash=_string(row, "content_hash"),
        schema_json=_optional_mapping(row, "schema_json"),
        row_count=_optional_integer(row, "row_count"),
        chunk_count=_optional_integer(row, "chunk_count"),
        error_reason=_optional_string(row, "error_reason"),
        session_id=_optional_string(row, "session_id"),
        promoted_to_doc_id=_optional_string(row, "promoted_to_doc_id"),
        last_accessed_at=_optional_datetime(row, "last_accessed_at"),
        expires_at=_optional_datetime(row, "expires_at"),
        deleted_at=_optional_datetime(row, "deleted_at"),
        archived_at=_optional_datetime(row, "archived_at"),
    )


def share_to_row(share: FileShareRecord) -> Mapping[str, object | None]:
    return {
        "share_id": share.share_id,
        "file_id": share.file_id,
        "granted_by": share.granted_by,
        "granted_to": share.granted_to,
        "permission": share.permission,
        "created_at": share.created_at,
        "revoked_at": share.revoked_at,
    }


def share_from_row(row: Mapping[str, object]) -> FileShareRecord:
    return FileShareRecord(
        share_id=_string(row, "share_id"),
        file_id=_string(row, "file_id"),
        granted_by=_string(row, "granted_by"),
        granted_to=_string(row, "granted_to"),
        created_at=_datetime(row, "created_at"),
        permission=cast(SharePermission, _string(row, "permission")),
        revoked_at=_optional_datetime(row, "revoked_at"),
    )


def share_request_to_row(request: FileShareRequest) -> Mapping[str, object | None]:
    return {
        "request_id": request.request_id,
        "file_id": request.file_id,
        "requested_by": request.requested_by,
        "org_id": request.org_id,
        "role": request.role,
        "status": request.status,
        "requested_at": request.requested_at,
        "decided_by": request.decided_by,
        "decided_at": request.decided_at,
        "reason": request.reason,
    }


def share_request_from_row(row: Mapping[str, object]) -> FileShareRequest:
    return FileShareRequest(
        request_id=_string(row, "request_id"),
        file_id=_string(row, "file_id"),
        requested_by=_string(row, "requested_by"),
        org_id=_string(row, "org_id"),
        role=_string(row, "role"),
        status=cast(FileShareRequestStatus, _string(row, "status")),
        requested_at=_datetime(row, "requested_at"),
        decided_by=_optional_string(row, "decided_by"),
        decided_at=_optional_datetime(row, "decided_at"),
        reason=_optional_string(row, "reason"),
    )


def _string(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(row: Mapping[str, object], field_name: str) -> str | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or None")
    return value


def _integer(row: Mapping[str, object], field_name: str) -> int:
    value = row.get(field_name)
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _optional_integer(row: Mapping[str, object], field_name: str) -> int | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer or None")
    return value


def _bool(row: Mapping[str, object], field_name: str) -> bool:
    value = row.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _datetime(row: Mapping[str, object], field_name: str) -> datetime:
    value = row.get(field_name)
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    return value


def _optional_datetime(row: Mapping[str, object], field_name: str) -> datetime | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime or None")
    return value


def _optional_mapping(row: Mapping[str, object], field_name: str) -> Mapping[str, Any] | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object or None")
    return cast(Mapping[str, Any], value)
