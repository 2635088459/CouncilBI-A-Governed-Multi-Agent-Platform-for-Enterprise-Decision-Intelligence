import pytest

from chatbi.files import (
    FileFormatCheckResult,
    FileFormatValidator,
    FileSizeCheckResult,
    FileSizeEnforcer,
    MimeCheckResult,
    MimeMagicChecker,
    StorageQuotaCheckResult,
    StorageQuotaEnforcer,
)


ALLOWED_EXTENSIONS = ("csv", "xlsx", "xls", "tsv", "json", "pdf", "docx", "txt", "md", "pptx")
BLOCKED_EXTENSIONS = ("exe", "sh", "py", "zip", "tar", "sql", "js")


@pytest.mark.parametrize("extension", ALLOWED_EXTENSIONS)
def test_file_format_validator_allows_whitelisted_extensions(extension: str) -> None:
    result = FileFormatValidator().validate(f"report.{extension}")

    assert result == FileFormatCheckResult.ALLOWED


@pytest.mark.parametrize("extension", BLOCKED_EXTENSIONS)
def test_file_format_validator_blocks_non_whitelisted_extensions(extension: str) -> None:
    result = FileFormatValidator().validate(f"payload.{extension}")

    assert result == FileFormatCheckResult.BLOCKED


def test_mime_magic_checker_flags_pdf_magic_bytes_in_csv_file() -> None:
    result = MimeMagicChecker().check("report.csv", b"%PDF-1.4 rest of file")

    assert result == MimeCheckResult.MISMATCH


def test_mime_magic_checker_allows_ascii_text_csv_file() -> None:
    result = MimeMagicChecker().check("report.csv", b"col_a,col_b\n1,2\n")

    assert result == MimeCheckResult.OK


def test_file_size_enforcer_blocks_business_user_file_over_50mb() -> None:
    result = FileSizeEnforcer().check(role="business_user", size=52_428_801)

    assert result == FileSizeCheckResult.EXCEEDS_PER_FILE_LIMIT


def test_file_size_enforcer_blocks_analyst_file_over_500mb() -> None:
    result = FileSizeEnforcer().check(role="analyst", size=524_288_001)

    assert result == FileSizeCheckResult.EXCEEDS_PER_FILE_LIMIT


def test_file_size_enforcer_allows_admin_file_at_2gb_boundary() -> None:
    result = FileSizeEnforcer().check(role="admin", size=2_147_483_648)

    assert result == FileSizeCheckResult.OK


def test_storage_quota_enforcer_blocks_business_user_at_quota_boundary() -> None:
    result = StorageQuotaEnforcer().check(role="business_user", used=524_288_000, adding=1)

    assert result == StorageQuotaCheckResult.EXCEEDS_QUOTA
