"""PostgreSQL CRUD boundary for ``user_uploaded_files`` and ``user_file_shares``.

Defines the repository port first, then provides an in-memory implementation
for tests and a PostgreSQL implementation for production. Access control
(FR-FV10-036) and version bookkeeping (FR-FV10-029) are layered on top of
this module by ``access.py`` and ``versioning.py`` — this file only persists
and retrieves rows.
"""

from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol, Sequence, cast

from chatbi.files.contracts import (
    FileScope,
    FileShareRecord,
    FileShareRequest,
    FileShareRequestStatus,
    FileStatus,
    FileType,
    UserUploadedFile,
)
from chatbi.files.postgres_rows import (
    FILE_UPLOAD_TABLES_SQL,
    file_from_row,
    file_to_row,
    share_from_row,
    share_request_from_row,
    share_request_to_row,
    share_to_row,
)


class FileRepository(Protocol):
    """Storage port for uploaded file metadata and share grants."""

    def save(self, file: UserUploadedFile) -> None:
        """Insert a new file record, or overwrite an existing one by file_id."""
        ...

    def get(self, file_id: str) -> UserUploadedFile | None:
        """Return one file record regardless of ownership or scope."""
        ...

    def soft_delete(self, file_id: str, *, deleted_at: datetime) -> None:
        """Mark a file as deleted without removing its metadata row."""
        ...

    def hard_delete(self, file_id: str) -> None:
        """Irreversibly remove a file's metadata row (FR-FV10-049 dedup purge).

        Unlike ``soft_delete``, this actually deletes the row. Only ever
        called for an *archived* duplicate a user just proved they still
        want by re-uploading its exact bytes.
        """
        ...

    def list_by_owner(
        self,
        org_id: str,
        user_id: str,
        *,
        scope: FileScope | None = None,
        status: FileStatus | None = None,
        all_versions: bool = False,
    ) -> tuple[UserUploadedFile, ...]:
        """Return one user's own non-archived files, newest first (FR-FV10-011).

        Archived files are excluded (Spec FV10.3 §3): they no longer belong
        to the owner's usable working set.
        """
        ...

    def find_archived_by_content_hash(
        self, user_id: str, content_hash: str
    ) -> UserUploadedFile | None:
        """Return an archived file owned by ``user_id`` with this ``content_hash``.

        FR-FV10-049/NFR-FV10-017: scoped to the *same* uploader only.
        """
        ...

    def list_archived_by_org(self, org_id: str) -> tuple[UserUploadedFile, ...]:
        """Return every archived file in an org, newest-archived first (§6.4)."""
        ...

    def list_versions(self, file_group_id: str) -> tuple[UserUploadedFile, ...]:
        """Return every version in a file's version chain, newest first."""
        ...

    def list_active(self) -> tuple[UserUploadedFile, ...]:
        """Return every non-deleted file record across all owners.

        Used by background jobs (retention, promotion) that must scan the
        whole table rather than one user's files.
        """
        ...

    def list_by_org(
        self,
        org_id: str,
        *,
        user_id: str | None = None,
        status: FileStatus | None = None,
        file_type: FileType | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[UserUploadedFile, ...]:
        """Return one page of the org's latest file versions, across all uploaders.

        Powers the admin review dashboard: ``user_id`` and ``q`` are
        substring/ILIKE matches (uploader search, filename search), newest
        first. See ``count_by_org`` for the matching total.
        """
        ...

    def count_by_org(
        self,
        org_id: str,
        *,
        user_id: str | None = None,
        status: FileStatus | None = None,
        file_type: FileType | None = None,
        q: str | None = None,
    ) -> int:
        """Return the total match count for the same filters as ``list_by_org``."""
        ...

    def save_share(self, share: FileShareRecord) -> None:
        """Insert a new share grant, or overwrite an existing one by share_id."""
        ...

    def save_shares(self, shares: Sequence[FileShareRecord]) -> None:
        """Insert every share grant as one unit (NFR-FV10-013): either all of
        ``shares`` land, or (on failure) none do. An empty sequence is a no-op.
        """
        ...

    def revoke_share(self, share_id: str, *, revoked_at: datetime) -> None:
        """Revoke a share grant. Idempotent: revoking twice is a no-op."""
        ...

    def share_by_id(self, share_id: str) -> FileShareRecord | None:
        ...

    def shares_for_file(self, file_id: str) -> tuple[FileShareRecord, ...]:
        ...

    def save_share_request(self, request: FileShareRequest) -> None:
        """Insert a new share request, or overwrite an existing one by request_id."""
        ...

    def share_request_by_id(self, request_id: str) -> FileShareRequest | None:
        ...

    def pending_share_request_for_file(self, file_id: str) -> FileShareRequest | None:
        """Return the active ``pending`` request for a file, if any (FR-FV10-041)."""
        ...

    def list_share_requests(
        self,
        org_id: str,
        *,
        status: FileShareRequestStatus | None = None,
    ) -> tuple[FileShareRequest, ...]:
        """Return an org's share requests, newest first, optionally filtered by status."""
        ...


class InMemoryFileRepository:
    """Simple repository implementation with PostgreSQL-shaped filtering."""

    def __init__(self) -> None:
        self._files_by_id: dict[str, UserUploadedFile] = {}
        self._shares_by_id: dict[str, FileShareRecord] = {}
        self._share_requests_by_id: dict[str, FileShareRequest] = {}

    def save(self, file: UserUploadedFile) -> None:
        self._files_by_id[file.file_id] = file

    def get(self, file_id: str) -> UserUploadedFile | None:
        return self._files_by_id.get(file_id)

    def soft_delete(self, file_id: str, *, deleted_at: datetime) -> None:
        file = self._files_by_id.get(file_id)
        if file is None:
            return
        self._files_by_id[file_id] = replace(file, deleted_at=deleted_at)

    def hard_delete(self, file_id: str) -> None:
        self._files_by_id.pop(file_id, None)

    def list_by_owner(
        self,
        org_id: str,
        user_id: str,
        *,
        scope: FileScope | None = None,
        status: FileStatus | None = None,
        all_versions: bool = False,
    ) -> tuple[UserUploadedFile, ...]:
        matches = [
            file
            for file in self._files_by_id.values()
            if file.org_id == org_id
            and file.user_id == user_id
            and file.deleted_at is None
            and file.archived_at is None
            and (all_versions or file.is_latest)
            and (scope is None or file.scope == scope)
            and (status is None or file.status == status)
        ]
        return tuple(sorted(matches, key=lambda file: file.created_at, reverse=True))

    def find_archived_by_content_hash(
        self, user_id: str, content_hash: str
    ) -> UserUploadedFile | None:
        for file in self._files_by_id.values():
            if (
                file.user_id == user_id
                and file.content_hash == content_hash
                and file.archived_at is not None
            ):
                return file
        return None

    def list_archived_by_org(self, org_id: str) -> tuple[UserUploadedFile, ...]:
        matches = [
            file
            for file in self._files_by_id.values()
            if file.org_id == org_id and file.archived_at is not None
        ]
        return tuple(sorted(matches, key=lambda file: cast(datetime, file.archived_at), reverse=True))

    def list_versions(self, file_group_id: str) -> tuple[UserUploadedFile, ...]:
        matches = [
            file for file in self._files_by_id.values() if file.file_group_id == file_group_id
        ]
        return tuple(sorted(matches, key=lambda file: file.version_number, reverse=True))

    def list_active(self) -> tuple[UserUploadedFile, ...]:
        matches = [file for file in self._files_by_id.values() if file.deleted_at is None]
        return tuple(sorted(matches, key=lambda file: file.file_id))

    def list_by_org(
        self,
        org_id: str,
        *,
        user_id: str | None = None,
        status: FileStatus | None = None,
        file_type: FileType | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[UserUploadedFile, ...]:
        matches = self._org_matches(org_id, user_id=user_id, status=status, file_type=file_type, q=q)
        return tuple(matches[offset : offset + limit])

    def count_by_org(
        self,
        org_id: str,
        *,
        user_id: str | None = None,
        status: FileStatus | None = None,
        file_type: FileType | None = None,
        q: str | None = None,
    ) -> int:
        return len(self._org_matches(org_id, user_id=user_id, status=status, file_type=file_type, q=q))

    def _org_matches(
        self,
        org_id: str,
        *,
        user_id: str | None,
        status: FileStatus | None,
        file_type: FileType | None,
        q: str | None,
    ) -> list[UserUploadedFile]:
        matches = [
            file
            for file in self._files_by_id.values()
            if file.org_id == org_id
            and file.deleted_at is None
            and file.archived_at is None
            and file.is_latest
            and (user_id is None or user_id.lower() in file.user_id.lower())
            and (status is None or file.status == status)
            and (file_type is None or file.file_type == file_type)
            and (q is None or q.lower() in file.original_name.lower())
        ]
        return sorted(matches, key=lambda file: file.created_at, reverse=True)

    def save_share(self, share: FileShareRecord) -> None:
        self._shares_by_id[share.share_id] = share

    def save_shares(self, shares: Sequence[FileShareRecord]) -> None:
        for share in shares:
            self._shares_by_id[share.share_id] = share

    def revoke_share(self, share_id: str, *, revoked_at: datetime) -> None:
        share = self._shares_by_id.get(share_id)
        if share is None or share.revoked_at is not None:
            return
        self._shares_by_id[share_id] = replace(share, revoked_at=revoked_at)

    def share_by_id(self, share_id: str) -> FileShareRecord | None:
        return self._shares_by_id.get(share_id)

    def shares_for_file(self, file_id: str) -> tuple[FileShareRecord, ...]:
        matches = [share for share in self._shares_by_id.values() if share.file_id == file_id]
        return tuple(sorted(matches, key=lambda share: share.created_at))

    def save_share_request(self, request: FileShareRequest) -> None:
        self._share_requests_by_id[request.request_id] = request

    def share_request_by_id(self, request_id: str) -> FileShareRequest | None:
        return self._share_requests_by_id.get(request_id)

    def pending_share_request_for_file(self, file_id: str) -> FileShareRequest | None:
        for request in self._share_requests_by_id.values():
            if request.file_id == file_id and request.status == "pending":
                return request
        return None

    def list_share_requests(
        self,
        org_id: str,
        *,
        status: FileShareRequestStatus | None = None,
    ) -> tuple[FileShareRequest, ...]:
        matches = [
            request
            for request in self._share_requests_by_id.values()
            if request.org_id == org_id and (status is None or request.status == status)
        ]
        return tuple(sorted(matches, key=lambda request: request.requested_at, reverse=True))


class FilePostgresConnection(Protocol):
    """Tiny DB-API style connection shape used by PostgresFileRepository."""

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any: ...

    def fetchone(self) -> Sequence[object] | None: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PsycopgFileConnection:
    """Adapt a psycopg-style connection to the tiny repository protocol."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._latest_cursor: Any | None = None

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        self._latest_cursor = self._connection.execute(sql, params)
        return self._latest_cursor

    def fetchone(self) -> Sequence[object] | None:
        if self._latest_cursor is None:
            return None
        return cast(Sequence[object] | None, self._latest_cursor.fetchone())

    def fetchall(self) -> Sequence[Sequence[object]]:
        if self._latest_cursor is None:
            return ()
        return cast(Sequence[Sequence[object]], self._latest_cursor.fetchall())

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


_FILE_COLUMNS = (
    "file_id",
    "org_id",
    "user_id",
    "original_name",
    "file_type",
    "mime_type",
    "size_bytes",
    "storage_key",
    "schema_json",
    "row_count",
    "chunk_count",
    "status",
    "error_reason",
    "scope",
    "session_id",
    "file_group_id",
    "version_number",
    "is_latest",
    "promoted_to_doc_id",
    "created_at",
    "last_accessed_at",
    "expires_at",
    "deleted_at",
    "content_hash",
    "archived_at",
)

_SHARE_COLUMNS = (
    "share_id",
    "file_id",
    "granted_by",
    "granted_to",
    "permission",
    "created_at",
    "revoked_at",
)

_SHARE_REQUEST_COLUMNS = (
    "request_id",
    "file_id",
    "requested_by",
    "org_id",
    "role",
    "status",
    "requested_at",
    "decided_by",
    "decided_at",
    "reason",
)


class PostgresFileRepository:
    """PostgreSQL implementation of the file repository boundary."""

    def __init__(self, connection: FilePostgresConnection) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        self._connection.execute(FILE_UPLOAD_TABLES_SQL)
        self._connection.commit()

    def save(self, file: UserUploadedFile) -> None:
        row = dict(file_to_row(file))
        if row["schema_json"] is not None:
            row["schema_json"] = _jsonb(row["schema_json"])
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in _FILE_COLUMNS[1:])
        placeholders = ", ".join(["%s"] * len(_FILE_COLUMNS))
        self._connection.execute(
            f"""
            INSERT INTO user_uploaded_files ({", ".join(_FILE_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT (file_id) DO UPDATE SET {assignments}
            """,
            tuple(row[column] for column in _FILE_COLUMNS),
        )
        self._connection.commit()

    def get(self, file_id: str) -> UserUploadedFile | None:
        self._connection.execute(
            f"SELECT {', '.join(_FILE_COLUMNS)} FROM user_uploaded_files WHERE file_id = %s",
            (file_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return file_from_row(_row_mapping(_FILE_COLUMNS, row))

    def soft_delete(self, file_id: str, *, deleted_at: datetime) -> None:
        self._connection.execute(
            "UPDATE user_uploaded_files SET deleted_at = %s WHERE file_id = %s",
            (deleted_at, file_id),
        )
        self._connection.commit()

    def hard_delete(self, file_id: str) -> None:
        self._connection.execute(
            "DELETE FROM user_uploaded_files WHERE file_id = %s",
            (file_id,),
        )
        self._connection.commit()

    def list_by_owner(
        self,
        org_id: str,
        user_id: str,
        *,
        scope: FileScope | None = None,
        status: FileStatus | None = None,
        all_versions: bool = False,
    ) -> tuple[UserUploadedFile, ...]:
        conditions = ["org_id = %s", "user_id = %s", "deleted_at IS NULL", "archived_at IS NULL"]
        params: list[object] = [org_id, user_id]
        if not all_versions:
            conditions.append("is_latest = TRUE")
        if scope is not None:
            conditions.append("scope = %s")
            params.append(scope)
        if status is not None:
            conditions.append("status = %s")
            params.append(status)

        self._connection.execute(
            f"""
            SELECT {', '.join(_FILE_COLUMNS)}
            FROM user_uploaded_files
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            """,
            tuple(params),
        )
        return tuple(
            file_from_row(_row_mapping(_FILE_COLUMNS, row)) for row in self._connection.fetchall()
        )

    def list_versions(self, file_group_id: str) -> tuple[UserUploadedFile, ...]:
        self._connection.execute(
            f"""
            SELECT {', '.join(_FILE_COLUMNS)}
            FROM user_uploaded_files
            WHERE file_group_id = %s
            ORDER BY version_number DESC
            """,
            (file_group_id,),
        )
        return tuple(
            file_from_row(_row_mapping(_FILE_COLUMNS, row)) for row in self._connection.fetchall()
        )

    def list_active(self) -> tuple[UserUploadedFile, ...]:
        self._connection.execute(
            f"""
            SELECT {', '.join(_FILE_COLUMNS)}
            FROM user_uploaded_files
            WHERE deleted_at IS NULL
            ORDER BY file_id ASC
            """
        )
        return tuple(
            file_from_row(_row_mapping(_FILE_COLUMNS, row)) for row in self._connection.fetchall()
        )

    def find_archived_by_content_hash(
        self, user_id: str, content_hash: str
    ) -> UserUploadedFile | None:
        self._connection.execute(
            f"""
            SELECT {', '.join(_FILE_COLUMNS)}
            FROM user_uploaded_files
            WHERE user_id = %s AND content_hash = %s AND archived_at IS NOT NULL
            LIMIT 1
            """,
            (user_id, content_hash),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return file_from_row(_row_mapping(_FILE_COLUMNS, row))

    def list_archived_by_org(self, org_id: str) -> tuple[UserUploadedFile, ...]:
        self._connection.execute(
            f"""
            SELECT {', '.join(_FILE_COLUMNS)}
            FROM user_uploaded_files
            WHERE org_id = %s AND archived_at IS NOT NULL
            ORDER BY archived_at DESC
            """,
            (org_id,),
        )
        return tuple(
            file_from_row(_row_mapping(_FILE_COLUMNS, row)) for row in self._connection.fetchall()
        )

    def list_by_org(
        self,
        org_id: str,
        *,
        user_id: str | None = None,
        status: FileStatus | None = None,
        file_type: FileType | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[UserUploadedFile, ...]:
        conditions, params = self._org_conditions(
            org_id, user_id=user_id, status=status, file_type=file_type, q=q
        )
        params = [*params, limit, offset]
        self._connection.execute(
            f"""
            SELECT {', '.join(_FILE_COLUMNS)}
            FROM user_uploaded_files
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return tuple(
            file_from_row(_row_mapping(_FILE_COLUMNS, row)) for row in self._connection.fetchall()
        )

    def count_by_org(
        self,
        org_id: str,
        *,
        user_id: str | None = None,
        status: FileStatus | None = None,
        file_type: FileType | None = None,
        q: str | None = None,
    ) -> int:
        conditions, params = self._org_conditions(
            org_id, user_id=user_id, status=status, file_type=file_type, q=q
        )
        self._connection.execute(
            f"SELECT COUNT(*) FROM user_uploaded_files WHERE {' AND '.join(conditions)}",
            tuple(params),
        )
        row = self._connection.fetchone()
        return int(cast(Any, row[0])) if row else 0

    def _org_conditions(
        self,
        org_id: str,
        *,
        user_id: str | None,
        status: FileStatus | None,
        file_type: FileType | None,
        q: str | None,
    ) -> tuple[list[str], list[object]]:
        conditions = ["org_id = %s", "deleted_at IS NULL", "archived_at IS NULL", "is_latest = TRUE"]
        params: list[object] = [org_id]
        if user_id is not None:
            conditions.append("user_id ILIKE %s")
            params.append(f"%{user_id}%")
        if status is not None:
            conditions.append("status = %s")
            params.append(status)
        if file_type is not None:
            conditions.append("file_type = %s")
            params.append(file_type)
        if q is not None:
            conditions.append("original_name ILIKE %s")
            params.append(f"%{q}%")
        return conditions, params

    def save_share(self, share: FileShareRecord) -> None:
        row = share_to_row(share)
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in _SHARE_COLUMNS[1:])
        placeholders = ", ".join(["%s"] * len(_SHARE_COLUMNS))
        self._connection.execute(
            f"""
            INSERT INTO user_file_shares ({", ".join(_SHARE_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT (share_id) DO UPDATE SET {assignments}
            """,
            tuple(row[column] for column in _SHARE_COLUMNS),
        )
        self._connection.commit()

    def revoke_share(self, share_id: str, *, revoked_at: datetime) -> None:
        self._connection.execute(
            "UPDATE user_file_shares SET revoked_at = %s WHERE share_id = %s AND revoked_at IS NULL",
            (revoked_at, share_id),
        )
        self._connection.commit()

    def share_by_id(self, share_id: str) -> FileShareRecord | None:
        self._connection.execute(
            f"SELECT {', '.join(_SHARE_COLUMNS)} FROM user_file_shares WHERE share_id = %s",
            (share_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return share_from_row(_row_mapping(_SHARE_COLUMNS, row))

    def shares_for_file(self, file_id: str) -> tuple[FileShareRecord, ...]:
        self._connection.execute(
            f"""
            SELECT {', '.join(_SHARE_COLUMNS)}
            FROM user_file_shares
            WHERE file_id = %s
            ORDER BY created_at ASC
            """,
            (file_id,),
        )
        return tuple(
            share_from_row(_row_mapping(_SHARE_COLUMNS, row)) for row in self._connection.fetchall()
        )

    def save_shares(self, shares: Sequence[FileShareRecord]) -> None:
        if not shares:
            return
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in _SHARE_COLUMNS[1:])
        placeholders = ", ".join(["%s"] * len(_SHARE_COLUMNS))
        try:
            for share in shares:
                row = share_to_row(share)
                self._connection.execute(
                    f"""
                    INSERT INTO user_file_shares ({", ".join(_SHARE_COLUMNS)})
                    VALUES ({placeholders})
                    ON CONFLICT (share_id) DO UPDATE SET {assignments}
                    """,
                    tuple(row[column] for column in _SHARE_COLUMNS),
                )
        except Exception:
            self._connection.rollback()
            raise
        self._connection.commit()

    def save_share_request(self, request: FileShareRequest) -> None:
        row = share_request_to_row(request)
        assignments = ", ".join(
            f"{column} = EXCLUDED.{column}" for column in _SHARE_REQUEST_COLUMNS[1:]
        )
        placeholders = ", ".join(["%s"] * len(_SHARE_REQUEST_COLUMNS))
        self._connection.execute(
            f"""
            INSERT INTO file_share_requests ({", ".join(_SHARE_REQUEST_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT (request_id) DO UPDATE SET {assignments}
            """,
            tuple(row[column] for column in _SHARE_REQUEST_COLUMNS),
        )
        self._connection.commit()

    def share_request_by_id(self, request_id: str) -> FileShareRequest | None:
        self._connection.execute(
            f"SELECT {', '.join(_SHARE_REQUEST_COLUMNS)} FROM file_share_requests WHERE request_id = %s",
            (request_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return share_request_from_row(_row_mapping(_SHARE_REQUEST_COLUMNS, row))

    def pending_share_request_for_file(self, file_id: str) -> FileShareRequest | None:
        self._connection.execute(
            f"""
            SELECT {', '.join(_SHARE_REQUEST_COLUMNS)}
            FROM file_share_requests
            WHERE file_id = %s AND status = 'pending'
            LIMIT 1
            """,
            (file_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return share_request_from_row(_row_mapping(_SHARE_REQUEST_COLUMNS, row))

    def list_share_requests(
        self,
        org_id: str,
        *,
        status: FileShareRequestStatus | None = None,
    ) -> tuple[FileShareRequest, ...]:
        conditions = ["org_id = %s"]
        params: list[object] = [org_id]
        if status is not None:
            conditions.append("status = %s")
            params.append(status)
        self._connection.execute(
            f"""
            SELECT {', '.join(_SHARE_REQUEST_COLUMNS)}
            FROM file_share_requests
            WHERE {' AND '.join(conditions)}
            ORDER BY requested_at DESC
            """,
            tuple(params),
        )
        return tuple(
            share_request_from_row(_row_mapping(_SHARE_REQUEST_COLUMNS, row))
            for row in self._connection.fetchall()
        )


def postgres_file_repository_from_psycopg(connection: Any) -> PostgresFileRepository:
    """Build a PostgreSQL file repository from a psycopg-style connection."""

    return PostgresFileRepository(PsycopgFileConnection(connection))


def connect_psycopg(database_url: str) -> Any:
    """Open a psycopg connection without making psycopg a hard import at module load."""

    psycopg = importlib.import_module("psycopg")
    return psycopg.connect(database_url)


def _jsonb(value: object) -> Any:
    """Wrap a dict for a JSONB column; psycopg does not adapt plain dicts."""

    json_types = importlib.import_module("psycopg.types.json")
    return json_types.Jsonb(value)


def _row_mapping(columns: tuple[str, ...], row: Sequence[object]) -> dict[str, object]:
    if len(row) != len(columns):
        raise ValueError("file repository row has unexpected column count.")
    return dict(zip(columns, row, strict=True))
