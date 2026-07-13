"""Upload-time validation for the user file upload pipeline.

This module covers the checks that must run before any object storage write:
extension whitelisting, declared-type-vs-magic-bytes verification, per-file
size limits, and cumulative storage quotas. See
``spec/final-version/en/10-user-file-upload-and-hybrid-analysis.spec.md``
FR-FV10-002 through FR-FV10-005.
"""

from __future__ import annotations

from enum import StrEnum

from chatbi.core.architecture_contracts import UserRoleV2


ALLOWED_FILE_EXTENSIONS = frozenset(
    {"csv", "xlsx", "xls", "tsv", "json", "pdf", "docx", "txt", "md", "pptx"}
)

_PDF_MAGIC = b"%PDF"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

_ZIP_OFFICE_EXTENSIONS = frozenset({"xlsx", "docx", "pptx"})
_OLE_OFFICE_EXTENSIONS = frozenset({"xls"})

_PER_FILE_SIZE_LIMITS_BYTES: dict[UserRoleV2, int] = {
    "business_user": 50 * 1024 * 1024,
    "analyst": 500 * 1024 * 1024,
    "admin": 2 * 1024 * 1024 * 1024,
}

_STORAGE_QUOTA_LIMITS_BYTES: dict[UserRoleV2, int] = {
    "business_user": 500 * 1024 * 1024,
    "analyst": 5 * 1024 * 1024 * 1024,
    "admin": 20 * 1024 * 1024 * 1024,
}


class FileFormatCheckResult(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class MimeCheckResult(StrEnum):
    OK = "ok"
    MISMATCH = "mismatch"


class FileSizeCheckResult(StrEnum):
    OK = "ok"
    EXCEEDS_PER_FILE_LIMIT = "exceeds_per_file_limit"


class StorageQuotaCheckResult(StrEnum):
    OK = "ok"
    EXCEEDS_QUOTA = "exceeds_quota"


class FileFormatValidator:
    """Reject any file extension outside the FR-FV10-002 whitelist."""

    def validate(self, filename: str) -> FileFormatCheckResult:
        extension = _extension_of(filename)
        if extension in ALLOWED_FILE_EXTENSIONS:
            return FileFormatCheckResult.ALLOWED
        return FileFormatCheckResult.BLOCKED


class MimeMagicChecker:
    """Detect a mismatch between a file's extension and its magic bytes."""

    def check(self, filename: str, content_bytes: bytes) -> MimeCheckResult:
        extension = _extension_of(filename)
        expected_family = _expected_family(extension)
        actual_family = _actual_family(content_bytes)

        if expected_family == "text":
            if actual_family in ("pdf", "zip_office", "ole_office"):
                return MimeCheckResult.MISMATCH
            return MimeCheckResult.OK

        if actual_family != expected_family:
            return MimeCheckResult.MISMATCH
        return MimeCheckResult.OK


class FileSizeEnforcer:
    """Enforce the per-file size limit for FR-FV10-004."""

    def check(self, role: UserRoleV2, size: int) -> FileSizeCheckResult:
        limit = _PER_FILE_SIZE_LIMITS_BYTES[role]
        if size > limit:
            return FileSizeCheckResult.EXCEEDS_PER_FILE_LIMIT
        return FileSizeCheckResult.OK


class StorageQuotaEnforcer:
    """Enforce the cumulative per-user storage quota for FR-FV10-005."""

    def check(self, role: UserRoleV2, used: int, adding: int) -> StorageQuotaCheckResult:
        limit = _STORAGE_QUOTA_LIMITS_BYTES[role]
        if used + adding > limit:
            return StorageQuotaCheckResult.EXCEEDS_QUOTA
        return StorageQuotaCheckResult.OK


def _extension_of(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", maxsplit=1)[-1].lower()


def _expected_family(extension: str) -> str:
    if extension == "pdf":
        return "pdf"
    if extension in _ZIP_OFFICE_EXTENSIONS:
        return "zip_office"
    if extension in _OLE_OFFICE_EXTENSIONS:
        return "ole_office"
    return "text"


def _actual_family(content_bytes: bytes) -> str:
    if content_bytes.startswith(_PDF_MAGIC):
        return "pdf"
    if content_bytes[:4] in _ZIP_MAGICS:
        return "zip_office"
    if content_bytes[:8] == _OLE_MAGIC:
        return "ole_office"
    return "text"
