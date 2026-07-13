from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.auth import AuthService, SignUpRequest, TokenService
from chatbi.files import (
    ChunkUploadSession,
    ChunkUploadSessionStore,
    InMemoryChunkUploadSessionStore,
    InMemoryFileRepository,
    InMemoryFileVectorSink,
    InMemoryObjectStorageAdapter,
    UserUploadedFile,
)


def _admin_auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _build_client(
    repository: InMemoryFileRepository | None = None,
    storage: InMemoryObjectStorageAdapter | None = None,
    vector_sink: InMemoryFileVectorSink | None = None,
    auth_service: AuthService | None = None,
    chunk_upload_session_store: ChunkUploadSessionStore | None = None,
) -> tuple[Any, InMemoryFileRepository, InMemoryObjectStorageAdapter, InMemoryFileVectorSink]:
    active_repository = repository or InMemoryFileRepository()
    active_storage = storage or InMemoryObjectStorageAdapter()
    active_vector_sink = vector_sink or InMemoryFileVectorSink()
    app = create_app(
        file_repository=active_repository,
        object_storage_adapter=active_storage,
        file_vector_sink=active_vector_sink,
        auth_service=auth_service,
        chunk_upload_session_store=chunk_upload_session_store or InMemoryChunkUploadSessionStore(),
    )
    return TestClient(app), active_repository, active_storage, active_vector_sink


def _business_user_headers(auth_service: AuthService) -> dict[str, str]:
    _user, tokens = auth_service.sign_up(
        SignUpRequest(
            email="biz@example.com",
            password="correct horse battery staple",
            display_name="Biz User",
        )
    )
    return {"Authorization": f"Bearer {tokens.access_token}"}


def _valid_csv_bytes(row_count: int = 10) -> bytes:
    header = b"month,revenue\n"
    rows = b"".join(f"2026-{(i % 12) + 1:02d},{100 + i}.0\n".encode() for i in range(row_count))
    return header + rows


def _minimal_pdf_bytes(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        b"5 0 obj\n<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream\nendobj\n",
    ]
    buffer = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(buffer))
        buffer += obj
    xref_offset = len(buffer)
    buffer += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        buffer += ("%010d 00000 n \n" % offset).encode("latin-1")
    buffer += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (
        len(objects) + 1,
        xref_offset,
    )
    return bytes(buffer)


def test_upload_valid_csv_returns_202_with_file_id_and_processing_status() -> None:
    client, _repository, _storage, _sink = _build_client()

    response = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("revenue.csv", _valid_csv_bytes(10), "text/csv")},
        data={"scope": "user"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["data"]["file_id"].startswith("ufile_")
    assert body["data"]["status"] == "processing"


def test_get_file_after_upload_shows_ready_status_and_correct_row_count() -> None:
    client, _repository, _storage, _sink = _build_client()

    upload_response = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("revenue.csv", _valid_csv_bytes(10), "text/csv")},
        data={"scope": "user"},
    )
    file_id = upload_response.json()["data"]["file_id"]

    get_response = client.get(f"/api/v2/files/{file_id}", headers=_admin_auth_headers())

    assert get_response.status_code == 200
    data = get_response.json()["data"]
    assert data["status"] == "ready"
    assert data["schema_json"] is not None
    assert data["row_count"] == 10


def test_upload_blocked_extension_returns_422_without_any_storage_write() -> None:
    # The route validates the extension before ever calling put_object(), so
    # an empty repository after a 422 is direct evidence no write happened:
    # a successful upload always saves a record right after writing bytes.
    client, repository, _storage, _sink = _build_client()

    response = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("payload.exe", b"MZ\x90\x00fake binary", "application/octet-stream")},
        data={"scope": "user"},
    )

    assert response.status_code == 422
    assert repository.list_by_owner("org_test", "u_001", all_versions=True) == ()


def test_upload_declared_csv_with_pdf_bytes_returns_mime_mismatch() -> None:
    client, _repository, _storage, _sink = _build_client()

    response = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("report.csv", _minimal_pdf_bytes("hello"), "text/csv")},
        data={"scope": "user"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FILE_MIME_MISMATCH"


def test_business_user_upload_over_50mb_returns_413() -> None:
    auth_service = AuthService(token_service=TokenService(secret="test-secret"))
    client, _repository, _storage, _sink = _build_client(auth_service=auth_service)
    headers = _business_user_headers(auth_service)
    oversized_bytes = b"a" * (50 * 1024 * 1024 + 1)

    response = client.post(
        "/api/v2/files/upload",
        headers=headers,
        files={"file": ("notes.txt", oversized_bytes, "text/plain")},
        data={"scope": "user"},
    )

    assert response.status_code == 413


def test_upload_at_quota_returns_409_storage_quota_exceeded() -> None:
    auth_service = AuthService(token_service=TokenService(secret="test-secret"))
    repository = InMemoryFileRepository()
    client, _repository, _storage, _sink = _build_client(
        repository=repository, auth_service=auth_service
    )
    headers = _business_user_headers(auth_service)

    # Seed the business_user's usage to sit exactly at their 500MB quota.
    seeded_user_id = auth_service.store.get_user_by_email("biz@example.com")
    assert seeded_user_id is not None
    repository.save(
        UserUploadedFile(
            file_id="ufile_seed0000000000000000000001",
            org_id=seeded_user_id.org_id,
            user_id=seeded_user_id.user_id,
            original_name="existing.txt",
            file_type="unstructured",
            mime_type="text/plain",
            size_bytes=500 * 1024 * 1024,
            storage_key=f"{seeded_user_id.org_id}/{seeded_user_id.user_id}/ufile_seed/existing.txt",
            content_hash="hash_seed",
            status="ready",
            scope="user",
            file_group_id="fgrp_seed",
            version_number=1,
            is_latest=True,
            created_at=datetime.now(timezone.utc),
            chunk_count=1,
        )
    )

    response = client.post(
        "/api/v2/files/upload",
        headers=headers,
        files={"file": ("one_more.txt", b"just one more byte", "text/plain")},
        data={"scope": "user"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STORAGE_QUOTA_EXCEEDED"


def test_list_files_returns_only_the_authenticated_users_files() -> None:
    repository = InMemoryFileRepository()
    client, _repository, _storage, _sink = _build_client(repository=repository)
    repository.save(
        UserUploadedFile(
            file_id="ufile_otheruser000000000000000001",
            org_id="org_other",
            user_id="user_other",
            original_name="not_mine.csv",
            file_type="structured",
            mime_type="text/csv",
            size_bytes=10,
            storage_key="org_other/user_other/ufile_otheruser/not_mine.csv",
            content_hash="hash_otheruser",
            status="ready",
            scope="user",
            file_group_id="fgrp_other",
            version_number=1,
            is_latest=True,
            created_at=datetime.now(timezone.utc),
            schema_json={"columns": []},
            row_count=0,
        )
    )
    client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("mine.csv", _valid_csv_bytes(3), "text/csv")},
        data={"scope": "user"},
    )

    response = client.get("/api/v2/files", headers=_admin_auth_headers())

    assert response.status_code == 200
    file_names = {entry["original_name"] for entry in response.json()["data"]["files"]}
    assert file_names == {"mine.csv"}


def test_delete_file_soft_deletes_and_subsequent_get_returns_404() -> None:
    client, _repository, _storage, _sink = _build_client()
    upload_response = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("revenue.csv", _valid_csv_bytes(5), "text/csv")},
        data={"scope": "user"},
    )
    file_id = upload_response.json()["data"]["file_id"]

    delete_response = client.delete(f"/api/v2/files/{file_id}", headers=_admin_auth_headers())
    get_after_delete = client.get(f"/api/v2/files/{file_id}", headers=_admin_auth_headers())

    assert delete_response.status_code == 204
    assert get_after_delete.status_code == 404


def test_preview_structured_file_returns_first_50_of_200_rows() -> None:
    client, _repository, _storage, _sink = _build_client()
    upload_response = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("revenue.csv", _valid_csv_bytes(200), "text/csv")},
        data={"scope": "user"},
    )
    file_id = upload_response.json()["data"]["file_id"]

    response = client.get(f"/api/v2/files/{file_id}/preview", headers=_admin_auth_headers())

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["rows"]) == 50
    assert data["total_row_count"] == 200


def test_preview_unstructured_pdf_returns_first_3_chunk_texts() -> None:
    client, _repository, _storage, _sink = _build_client()
    pdf_text = (
        "Escalate P1 incidents immediately. Notify the on-call engineer. "
        "Document the timeline. Review root cause within 24 hours. "
        "File a postmortem within one week. Share learnings with the team. "
        "Close the incident once verified. Archive supporting logs."
    )
    upload_response = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("runbook.pdf", _minimal_pdf_bytes(pdf_text), "application/pdf")},
        data={"scope": "user"},
    )
    file_id = upload_response.json()["data"]["file_id"]

    response = client.get(f"/api/v2/files/{file_id}/preview", headers=_admin_auth_headers())

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["chunks"]) <= 3
    assert len(data["chunks"]) >= 1


def test_chunked_upload_init_returns_one_presigned_url_per_chunk() -> None:
    client, _repository, _storage, _sink = _build_client()
    file_size_bytes = 5 * 1024 * 1024 * 2 + 100  # forces chunk_count == 3

    response = client.post(
        "/api/v2/files/upload/init",
        headers=_admin_auth_headers(),
        json={
            "original_name": "big_forecast.csv",
            "file_size_bytes": file_size_bytes,
            "mime_type": "text/csv",
            "scope": "user",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["upload_id"].startswith("upl_")
    assert data["chunk_count"] == 3
    assert [entry["chunk_index"] for entry in data["presigned_urls"]] == [0, 1, 2]


def test_chunked_upload_complete_after_uploading_all_chunks_returns_processing() -> None:
    client, _repository, storage, _sink = _build_client()
    csv_bytes = _valid_csv_bytes(10)

    init_response = client.post(
        "/api/v2/files/upload/init",
        headers=_admin_auth_headers(),
        json={
            "original_name": "revenue.csv",
            "file_size_bytes": len(csv_bytes),
            "mime_type": "text/csv",
            "scope": "user",
        },
    )
    init_data = init_response.json()["data"]
    assert init_data["chunk_count"] == 1
    upload_id = init_data["upload_id"]
    chunk_url = init_data["presigned_urls"][0]["url"]

    etag = storage.upload_via_url(chunk_url, csv_bytes)

    complete_response = client.post(
        f"/api/v2/files/upload/{upload_id}/complete",
        headers=_admin_auth_headers(),
        json={"etags": [{"chunk_index": 0, "etag": etag}]},
    )

    assert complete_response.status_code == 202
    complete_data = complete_response.json()["data"]
    assert complete_data["file_id"].startswith("ufile_")
    assert complete_data["status"] == "processing"


def test_chunked_upload_produces_same_schema_as_single_shot_upload() -> None:
    client, _repository, storage, _sink = _build_client()
    csv_bytes = _valid_csv_bytes(10)

    single_shot_response = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("revenue_single.csv", csv_bytes, "text/csv")},
        data={"scope": "user"},
    )
    single_shot_file_id = single_shot_response.json()["data"]["file_id"]
    single_shot_schema = client.get(
        f"/api/v2/files/{single_shot_file_id}", headers=_admin_auth_headers()
    ).json()["data"]["schema_json"]

    init_response = client.post(
        "/api/v2/files/upload/init",
        headers=_admin_auth_headers(),
        json={
            "original_name": "revenue_chunked.csv",
            "file_size_bytes": len(csv_bytes),
            "mime_type": "text/csv",
            "scope": "user",
        },
    )
    init_data = init_response.json()["data"]
    upload_id = init_data["upload_id"]
    chunk_url = init_data["presigned_urls"][0]["url"]
    etag = storage.upload_via_url(chunk_url, csv_bytes)
    complete_response = client.post(
        f"/api/v2/files/upload/{upload_id}/complete",
        headers=_admin_auth_headers(),
        json={"etags": [{"chunk_index": 0, "etag": etag}]},
    )
    chunked_file_id = complete_response.json()["data"]["file_id"]
    chunked_schema = client.get(
        f"/api/v2/files/{chunked_file_id}", headers=_admin_auth_headers()
    ).json()["data"]["schema_json"]

    assert chunked_schema == single_shot_schema


def test_chunked_upload_complete_with_missing_chunk_etag_returns_422() -> None:
    client, _repository, _storage, _sink = _build_client()
    file_size_bytes = 5 * 1024 * 1024 + 1  # forces chunk_count == 2

    init_response = client.post(
        "/api/v2/files/upload/init",
        headers=_admin_auth_headers(),
        json={
            "original_name": "big_forecast.csv",
            "file_size_bytes": file_size_bytes,
            "mime_type": "text/csv",
            "scope": "user",
        },
    )
    upload_id = init_response.json()["data"]["upload_id"]

    complete_response = client.post(
        f"/api/v2/files/upload/{upload_id}/complete",
        headers=_admin_auth_headers(),
        json={"etags": [{"chunk_index": 0, "etag": "deadbeef"}]},
    )

    assert complete_response.status_code == 422


def test_reuploading_byte_identical_content_purges_the_same_users_archived_duplicate() -> None:
    # AC-FV10-042 / FR-FV10-049 / TC-FV10-133
    client, repository, storage, _sink = _build_client()
    csv_bytes = _valid_csv_bytes(5)
    first_upload = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("revenue.csv", csv_bytes, "text/csv")},
        data={"scope": "user"},
    )
    original_file_id = first_upload.json()["data"]["file_id"]
    original = repository.get(original_file_id)
    assert original is not None
    repository.save(replace(original, archived_at=datetime.now(timezone.utc)))
    assert storage.exists(original.storage_key)

    second_upload = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("revenue.csv", csv_bytes, "text/csv")},
        data={"scope": "user"},
    )

    assert second_upload.status_code == 202
    new_file_id = second_upload.json()["data"]["file_id"]
    assert new_file_id != original_file_id
    assert repository.get(original_file_id) is None
    assert not storage.exists(original.storage_key)
    assert repository.get(new_file_id) is not None


def test_reuploading_identical_content_as_a_different_user_does_not_purge_the_original_archive() -> None:
    # AC-FV10-043 / NFR-FV10-017 / TC-FV10-134
    auth_service = AuthService(token_service=TokenService(secret="test-secret"))
    client, repository, storage, _sink = _build_client(auth_service=auth_service)
    other_user_headers = _business_user_headers(auth_service)
    csv_bytes = _valid_csv_bytes(5)

    owner_upload = client.post(
        "/api/v2/files/upload",
        headers=_admin_auth_headers(),
        files={"file": ("revenue.csv", csv_bytes, "text/csv")},
        data={"scope": "user"},
    )
    owner_file_id = owner_upload.json()["data"]["file_id"]
    owner_file = repository.get(owner_file_id)
    assert owner_file is not None
    repository.save(replace(owner_file, archived_at=datetime.now(timezone.utc)))

    other_users_upload = client.post(
        "/api/v2/files/upload",
        headers=other_user_headers,
        files={"file": ("revenue.csv", csv_bytes, "text/csv")},
        data={"scope": "user"},
    )

    assert other_users_upload.status_code == 202
    assert repository.get(owner_file_id) is not None
    assert storage.exists(owner_file.storage_key)


def test_chunked_upload_complete_with_expired_session_returns_410() -> None:
    session_store = InMemoryChunkUploadSessionStore()
    client, _repository, _storage, _sink = _build_client(chunk_upload_session_store=session_store)
    expired_session = ChunkUploadSession(
        upload_id="upl_expired0000000000000000000001",
        org_id="org_test",
        user_id="u_001",
        original_name="revenue.csv",
        mime_type="text/csv",
        file_size_bytes=100,
        scope="user",
        chunk_size_bytes=5 * 1024 * 1024,
        chunk_count=1,
        chunk_keys=("org_test/u_001/_chunk_uploads/upl_expired/chunk_00000",),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    session_store.save(expired_session)

    response = client.post(
        "/api/v2/files/upload/upl_expired0000000000000000000001/complete",
        headers=_admin_auth_headers(),
        json={"etags": [{"chunk_index": 0, "etag": "deadbeef"}]},
    )

    assert response.status_code == 410
