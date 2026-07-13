"""Object storage abstraction for uploaded files (MinIO / S3 / mock).

Covers FR-FV10-006 (private storage, signed download URLs capped at 15
minutes), FR-FV10-013 (deleting the stored bytes on soft delete), and
NFR-FV10-006 (chunk upload URLs capped at 30 minutes, expired URLs rejected).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol
from uuid import uuid4


DEFAULT_BUCKET = "chatbi-user-files"
MAX_DOWNLOAD_URL_TTL = timedelta(minutes=15)
MAX_UPLOAD_URL_TTL = timedelta(minutes=30)


class ObjectNotFoundError(Exception):
    """Raised when a storage key or signed URL has no corresponding object."""


class PresignedUrlExpiredError(Exception):
    """Raised when a signed download or upload URL is used past its expiry."""


def sanitize_filename(filename: str) -> str:
    """Reduce a client-supplied filename to a bare basename (TC-FV10-101).

    Rejects path traversal by discarding any directory component, so a
    filename like ``../../../etc/passwd`` becomes ``passwd`` before it is
    ever used to build a storage key.
    """

    basename = PurePosixPath(filename.replace("\\", "/")).name
    if not basename or basename in (".", ".."):
        raise ValueError("filename must resolve to a non-empty basename")
    return basename


def build_storage_key(org_id: str, user_id: str, file_id: str, original_filename: str) -> str:
    """Build the FR-FV10-006 object key: ``{org_id}/{user_id}/{file_id}/{filename}``."""

    if not org_id.strip() or not user_id.strip() or not file_id.strip():
        raise ValueError("org_id, user_id, and file_id are required")
    safe_filename = sanitize_filename(original_filename)
    return f"{org_id}/{user_id}/{file_id}/{safe_filename}"


def parquet_storage_key(storage_key: str) -> str:
    """Derive the FR-FV10-008 Parquet snapshot key stored alongside the original file."""

    return f"{storage_key}.parquet"


@dataclass(frozen=True, slots=True)
class PresignedUrl:
    url: str
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        current_time = now if now is not None else datetime.now(timezone.utc)
        return current_time >= self.expires_at


class ObjectStorageAdapter(Protocol):
    """Backend-agnostic contract every storage adapter (MinIO/S3/mock) must satisfy."""

    def put_object(self, key: str, content: bytes) -> None: ...

    def get_object(self, key: str) -> bytes: ...

    def delete_object(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def generate_download_url(self, key: str, *, ttl: timedelta = MAX_DOWNLOAD_URL_TTL) -> PresignedUrl: ...

    def resolve_download_url(self, url: str) -> bytes: ...

    def generate_upload_url(self, key: str, *, ttl: timedelta = MAX_UPLOAD_URL_TTL) -> PresignedUrl: ...

    def upload_via_url(self, url: str, content: bytes) -> str: ...


class InMemoryObjectStorageAdapter:
    """In-process mock backend for tests and local development."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._objects: dict[str, bytes] = {}
        self._download_tokens: dict[str, tuple[str, datetime]] = {}
        self._upload_tokens: dict[str, tuple[str, datetime]] = {}
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def put_object(self, key: str, content: bytes) -> None:
        self._objects[key] = content

    def get_object(self, key: str) -> bytes:
        if key not in self._objects:
            raise ObjectNotFoundError(key)
        return self._objects[key]

    def delete_object(self, key: str) -> None:
        self._objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._objects

    def generate_download_url(self, key: str, *, ttl: timedelta = MAX_DOWNLOAD_URL_TTL) -> PresignedUrl:
        if ttl > MAX_DOWNLOAD_URL_TTL:
            raise ValueError("download URL ttl must not exceed 15 minutes")
        if key not in self._objects:
            raise ObjectNotFoundError(key)
        return self._issue_url(self._download_tokens, key, ttl, mode="download")

    def resolve_download_url(self, url: str) -> bytes:
        key = self._consume_token(self._download_tokens, url)
        return self.get_object(key)

    def generate_upload_url(self, key: str, *, ttl: timedelta = MAX_UPLOAD_URL_TTL) -> PresignedUrl:
        if ttl > MAX_UPLOAD_URL_TTL:
            raise ValueError("upload URL ttl must not exceed 30 minutes")
        return self._issue_url(self._upload_tokens, key, ttl, mode="upload")

    def upload_via_url(self, url: str, content: bytes) -> str:
        key = self._consume_token(self._upload_tokens, url)
        self._objects[key] = content
        return hashlib.md5(content).hexdigest()

    def _issue_url(
        self,
        token_store: dict[str, tuple[str, datetime]],
        key: str,
        ttl: timedelta,
        *,
        mode: str,
    ) -> PresignedUrl:
        token = f"tok_{uuid4().hex}"
        expires_at = self._clock() + ttl
        token_store[token] = (key, expires_at)
        url = f"mock://{DEFAULT_BUCKET}/{key}?mode={mode}&token={token}"
        return PresignedUrl(url=url, expires_at=expires_at)

    def _consume_token(self, token_store: dict[str, tuple[str, datetime]], url: str) -> str:
        token = url.rsplit("token=", maxsplit=1)[-1]
        entry = token_store.get(token)
        if entry is None:
            raise ObjectNotFoundError(url)
        key, expires_at = entry
        if self._clock() >= expires_at:
            raise PresignedUrlExpiredError(url)
        return key


class LocalDiskObjectStorageAdapter:
    """Disk-backed object storage: same contract as InMemoryObjectStorageAdapter,
    but bytes survive a process restart by living under ``root`` instead of
    in a Python dict. This is the local/single-node persistence path, not a
    substitute for a real object store (MinIO/S3) in a multi-instance
    production deployment.
    """

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._download_tokens: dict[str, tuple[str, datetime]] = {}
        self._upload_tokens: dict[str, tuple[str, datetime]] = {}
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def put_object(self, key: str, content: bytes) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def get_object(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return path.read_bytes()

    def delete_object(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

    def generate_download_url(self, key: str, *, ttl: timedelta = MAX_DOWNLOAD_URL_TTL) -> PresignedUrl:
        if ttl > MAX_DOWNLOAD_URL_TTL:
            raise ValueError("download URL ttl must not exceed 15 minutes")
        if not self.exists(key):
            raise ObjectNotFoundError(key)
        return self._issue_url(self._download_tokens, key, ttl, mode="download")

    def resolve_download_url(self, url: str) -> bytes:
        key = self._consume_token(self._download_tokens, url)
        return self.get_object(key)

    def generate_upload_url(self, key: str, *, ttl: timedelta = MAX_UPLOAD_URL_TTL) -> PresignedUrl:
        if ttl > MAX_UPLOAD_URL_TTL:
            raise ValueError("upload URL ttl must not exceed 30 minutes")
        return self._issue_url(self._upload_tokens, key, ttl, mode="upload")

    def upload_via_url(self, url: str, content: bytes) -> str:
        key = self._consume_token(self._upload_tokens, url)
        self.put_object(key, content)
        return hashlib.md5(content).hexdigest()

    def _path_for(self, key: str) -> Path:
        posix_key = PurePosixPath(key)
        if not key or key.startswith("/") or ".." in posix_key.parts:
            raise ValueError(f"unsafe storage key: {key!r}")
        return self._root / posix_key

    def _issue_url(
        self,
        token_store: dict[str, tuple[str, datetime]],
        key: str,
        ttl: timedelta,
        *,
        mode: str,
    ) -> PresignedUrl:
        token = f"tok_{uuid4().hex}"
        expires_at = self._clock() + ttl
        token_store[token] = (key, expires_at)
        url = f"file://{DEFAULT_BUCKET}/{key}?mode={mode}&token={token}"
        return PresignedUrl(url=url, expires_at=expires_at)

    def _consume_token(self, token_store: dict[str, tuple[str, datetime]], url: str) -> str:
        token = url.rsplit("token=", maxsplit=1)[-1]
        entry = token_store.get(token)
        if entry is None:
            raise ObjectNotFoundError(url)
        key, expires_at = entry
        if self._clock() >= expires_at:
            raise PresignedUrlExpiredError(url)
        return key
