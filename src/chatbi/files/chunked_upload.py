"""FR-FV10-031 chunked upload session bookkeeping.

The client uploads each chunk directly to object storage via a presigned PUT
URL (client -> MinIO/S3, bypassing the backend), so this module only tracks
what the server itself must remember between ``upload/init`` and
``upload/{upload_id}/complete``: which chunk keys were staged, how big the
final file should be, and when the whole session's presigned URLs expire
(NFR-FV10-006: 30 minutes; an expired session must fail with HTTP 410 at
complete time, not silently succeed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from chatbi.files.contracts import FileScope


DEFAULT_CHUNK_SIZE_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_SESSION_TTL = timedelta(minutes=30)


def new_upload_id() -> str:
    return f"upl_{uuid4().hex}"


def compute_chunk_count(file_size_bytes: int, chunk_size_bytes: int = DEFAULT_CHUNK_SIZE_BYTES) -> int:
    if file_size_bytes <= 0:
        raise ValueError("file_size_bytes must be greater than 0")
    return max(1, math.ceil(file_size_bytes / chunk_size_bytes))


def chunk_staging_key(org_id: str, user_id: str, upload_id: str, chunk_index: int) -> str:
    return f"{org_id}/{user_id}/_chunk_uploads/{upload_id}/chunk_{chunk_index:05d}"


@dataclass(frozen=True, slots=True)
class ChunkUploadSession:
    upload_id: str
    org_id: str
    user_id: str
    original_name: str
    mime_type: str
    file_size_bytes: int
    scope: FileScope
    chunk_size_bytes: int
    chunk_count: int
    chunk_keys: tuple[str, ...]
    expires_at: datetime
    session_id: str | None = None
    description: str | None = None

    def is_expired(self, *, now: datetime) -> bool:
        return now >= self.expires_at


class ChunkUploadSessionStore(Protocol):
    def save(self, session: ChunkUploadSession) -> None: ...

    def get(self, upload_id: str) -> ChunkUploadSession | None: ...

    def delete(self, upload_id: str) -> None: ...


class InMemoryChunkUploadSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ChunkUploadSession] = {}

    def save(self, session: ChunkUploadSession) -> None:
        self._sessions[session.upload_id] = session

    def get(self, upload_id: str) -> ChunkUploadSession | None:
        return self._sessions.get(upload_id)

    def delete(self, upload_id: str) -> None:
        self._sessions.pop(upload_id, None)
