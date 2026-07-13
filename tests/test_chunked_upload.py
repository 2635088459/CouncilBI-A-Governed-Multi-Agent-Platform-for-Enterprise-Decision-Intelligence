from datetime import datetime, timedelta, timezone

import pytest

from chatbi.files import (
    DEFAULT_CHUNK_SIZE_BYTES,
    ChunkUploadSession,
    InMemoryChunkUploadSessionStore,
    chunk_staging_key,
    compute_chunk_count,
    new_upload_id,
)


def test_new_upload_id_uses_required_prefix() -> None:
    upload_id = new_upload_id()

    assert upload_id.startswith("upl_")


def test_compute_chunk_count_matches_file_size_and_chunk_size() -> None:
    assert compute_chunk_count(DEFAULT_CHUNK_SIZE_BYTES * 3, DEFAULT_CHUNK_SIZE_BYTES) == 3
    assert compute_chunk_count(DEFAULT_CHUNK_SIZE_BYTES * 3 + 1, DEFAULT_CHUNK_SIZE_BYTES) == 4
    assert compute_chunk_count(1, DEFAULT_CHUNK_SIZE_BYTES) == 1


def test_compute_chunk_count_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError):
        compute_chunk_count(0)


def test_chunk_staging_key_is_scoped_by_org_user_and_upload_id() -> None:
    key = chunk_staging_key("org_1", "user_1", "upl_abc", 3)

    assert key == "org_1/user_1/_chunk_uploads/upl_abc/chunk_00003"


def _session(**overrides: object) -> ChunkUploadSession:
    fields: dict[str, object] = dict(
        upload_id="upl_abc",
        org_id="org_1",
        user_id="user_1",
        original_name="big_forecast.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_size_bytes=DEFAULT_CHUNK_SIZE_BYTES * 2,
        scope="user",
        chunk_size_bytes=DEFAULT_CHUNK_SIZE_BYTES,
        chunk_count=2,
        chunk_keys=("k0", "k1"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    fields.update(overrides)
    return ChunkUploadSession(**fields)  # type: ignore[arg-type]


def test_session_store_save_and_get_roundtrip() -> None:
    store = InMemoryChunkUploadSessionStore()
    session = _session()

    store.save(session)

    assert store.get("upl_abc") == session
    assert store.get("upl_missing") is None


def test_session_store_delete_removes_session() -> None:
    store = InMemoryChunkUploadSessionStore()
    store.save(_session())

    store.delete("upl_abc")

    assert store.get("upl_abc") is None


def test_session_is_expired_reflects_expires_at() -> None:
    now = datetime.now(timezone.utc)
    session = _session(expires_at=now + timedelta(minutes=1))

    assert session.is_expired(now=now + timedelta(minutes=2)) is True
    assert session.is_expired(now=now) is False
