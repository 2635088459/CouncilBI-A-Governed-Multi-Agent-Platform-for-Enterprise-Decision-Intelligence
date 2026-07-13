from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from chatbi.files import (
    InMemoryObjectStorageAdapter,
    LocalDiskObjectStorageAdapter,
    ObjectNotFoundError,
    PresignedUrlExpiredError,
    build_storage_key,
    sanitize_filename,
)


def test_sanitize_filename_strips_path_traversal_segments() -> None:
    assert sanitize_filename("../../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32\\config") == "config"


def test_sanitize_filename_rejects_names_with_no_basename() -> None:
    with pytest.raises(ValueError):
        sanitize_filename("../..")


def test_build_storage_key_matches_org_user_file_filename_layout() -> None:
    key = build_storage_key("org_1", "user_1", "ufile_abc", "../../etc/passwd")

    assert key == "org_1/user_1/ufile_abc/passwd"


def test_put_get_delete_roundtrip() -> None:
    adapter = InMemoryObjectStorageAdapter()
    adapter.put_object("org_1/user_1/ufile_abc/revenue.csv", b"a,b\n1,2\n")

    assert adapter.exists("org_1/user_1/ufile_abc/revenue.csv")
    assert adapter.get_object("org_1/user_1/ufile_abc/revenue.csv") == b"a,b\n1,2\n"

    adapter.delete_object("org_1/user_1/ufile_abc/revenue.csv")

    assert not adapter.exists("org_1/user_1/ufile_abc/revenue.csv")
    with pytest.raises(ObjectNotFoundError):
        adapter.get_object("org_1/user_1/ufile_abc/revenue.csv")


def test_download_url_ttl_cannot_exceed_15_minutes() -> None:
    adapter = InMemoryObjectStorageAdapter()
    adapter.put_object("k", b"data")

    with pytest.raises(ValueError, match="15 minutes"):
        adapter.generate_download_url("k", ttl=timedelta(minutes=16))


def test_download_url_works_before_expiry_and_fails_after() -> None:
    current_time = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return current_time

    adapter = InMemoryObjectStorageAdapter(clock=clock)
    adapter.put_object("k", b"secret-data")
    signed_url = adapter.generate_download_url("k", ttl=timedelta(minutes=15))

    assert adapter.resolve_download_url(signed_url.url) == b"secret-data"

    current_time = current_time + timedelta(minutes=15, seconds=1)
    with pytest.raises(PresignedUrlExpiredError):
        adapter.resolve_download_url(signed_url.url)


def test_upload_url_ttl_cannot_exceed_30_minutes() -> None:
    adapter = InMemoryObjectStorageAdapter()

    with pytest.raises(ValueError, match="30 minutes"):
        adapter.generate_upload_url("k", ttl=timedelta(minutes=31))


def test_upload_via_expired_url_raises_expired_error() -> None:
    current_time = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return current_time

    adapter = InMemoryObjectStorageAdapter(clock=clock)
    signed_url = adapter.generate_upload_url("k", ttl=timedelta(minutes=30))

    current_time = current_time + timedelta(minutes=30, seconds=1)
    with pytest.raises(PresignedUrlExpiredError):
        adapter.upload_via_url(signed_url.url, b"chunk-bytes")

    assert not adapter.exists("k")


def test_unknown_signed_url_raises_not_found() -> None:
    adapter = InMemoryObjectStorageAdapter()

    with pytest.raises(ObjectNotFoundError):
        adapter.resolve_download_url("mock://chatbi-user-files/k?mode=download&token=tok_nonexistent")


def test_local_disk_put_get_delete_roundtrip(tmp_path: Path) -> None:
    adapter = LocalDiskObjectStorageAdapter(tmp_path)
    adapter.put_object("org_1/user_1/ufile_abc/revenue.csv", b"a,b\n1,2\n")

    assert adapter.exists("org_1/user_1/ufile_abc/revenue.csv")
    assert adapter.get_object("org_1/user_1/ufile_abc/revenue.csv") == b"a,b\n1,2\n"

    adapter.delete_object("org_1/user_1/ufile_abc/revenue.csv")

    assert not adapter.exists("org_1/user_1/ufile_abc/revenue.csv")
    with pytest.raises(ObjectNotFoundError):
        adapter.get_object("org_1/user_1/ufile_abc/revenue.csv")


def test_local_disk_bytes_survive_a_fresh_adapter_instance_at_the_same_root(tmp_path: Path) -> None:
    """The whole point of this adapter: unlike InMemoryObjectStorageAdapter,
    re-pointing a brand new instance at the same root must still see
    previously written objects — this is what a backend process restart
    looks like."""

    first_process_adapter = LocalDiskObjectStorageAdapter(tmp_path)
    first_process_adapter.put_object("org_1/user_1/ufile_abc/revenue.csv", b"still-here")

    second_process_adapter = LocalDiskObjectStorageAdapter(tmp_path)

    assert second_process_adapter.exists("org_1/user_1/ufile_abc/revenue.csv")
    assert second_process_adapter.get_object("org_1/user_1/ufile_abc/revenue.csv") == b"still-here"


def test_local_disk_rejects_a_storage_key_that_escapes_the_root(tmp_path: Path) -> None:
    adapter = LocalDiskObjectStorageAdapter(tmp_path)

    with pytest.raises(ValueError, match="unsafe storage key"):
        adapter.put_object("../../etc/passwd", b"nope")


def test_local_disk_download_url_ttl_cannot_exceed_15_minutes(tmp_path: Path) -> None:
    adapter = LocalDiskObjectStorageAdapter(tmp_path)
    adapter.put_object("k", b"data")

    with pytest.raises(ValueError, match="15 minutes"):
        adapter.generate_download_url("k", ttl=timedelta(minutes=16))


def test_local_disk_download_url_works_before_expiry_and_fails_after(tmp_path: Path) -> None:
    current_time = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return current_time

    adapter = LocalDiskObjectStorageAdapter(tmp_path, clock=clock)
    adapter.put_object("k", b"secret-data")
    signed_url = adapter.generate_download_url("k", ttl=timedelta(minutes=15))

    assert adapter.resolve_download_url(signed_url.url) == b"secret-data"

    current_time = current_time + timedelta(minutes=15, seconds=1)
    with pytest.raises(PresignedUrlExpiredError):
        adapter.resolve_download_url(signed_url.url)


def test_local_disk_upload_via_url_writes_bytes_to_disk(tmp_path: Path) -> None:
    adapter = LocalDiskObjectStorageAdapter(tmp_path)
    signed_url = adapter.generate_upload_url("org_1/user_1/ufile_abc/chunk.bin")

    adapter.upload_via_url(signed_url.url, b"chunk-bytes")

    assert adapter.get_object("org_1/user_1/ufile_abc/chunk.bin") == b"chunk-bytes"
