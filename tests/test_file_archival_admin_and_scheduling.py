"""Spec FV10.3: admin archived-files visibility (§6.4) and retention
scheduling (FR-FV10-050)."""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.auth import AuthService, PasswordHasher, TokenService, permissions_for_roles
from chatbi.files import InMemoryFileRepository, InMemoryObjectStorageAdapter, UserUploadedFile


_PASSWORD = "correct horse battery staple"


def _admin_auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _seed_user(auth_service: AuthService, org_id: str, email: str, role: str) -> tuple[str, str]:
    hasher = PasswordHasher()
    user = auth_service.store.create_user(
        email=email,
        password_hash=hasher.hash_password(_PASSWORD),
        display_name=email,
        org_id=org_id,
        roles=(role,),
        permissions=permissions_for_roles((role,)),
    )
    _record, tokens = auth_service.sign_in(email, _PASSWORD)
    return user.user_id, tokens.access_token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_archived0000000000000000001",
        org_id="org_test",
        user_id="u_001",
        original_name="revenue.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=1024,
        storage_key="org_test/u_001/ufile_archived0000000000000000001/revenue.csv",
        content_hash="hash_archived",
        status="ready",
        scope="user",
        file_group_id="fgrp_archived",
        version_number=1,
        is_latest=True,
        created_at=datetime.now(timezone.utc) - timedelta(days=20),
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}]},
        row_count=1,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def test_admin_archived_files_endpoint_lists_only_archived_files_with_a_download_url() -> None:
    # AC-FV10-040
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    storage.put_object("org_test/u_001/ufile_archived0000000000000000001/revenue.csv", b"month\n2026-01\n")
    archived_file = _file(archived_at=datetime.now(timezone.utc))
    active_file = _file(
        file_id="ufile_active00000000000000000001",
        file_group_id="fgrp_active",
        archived_at=None,
    )
    repository.save(archived_file)
    repository.save(active_file)
    client: Any = TestClient(
        create_app(file_repository=repository, object_storage_adapter=storage)
    )

    response = client.get("/api/v2/admin/files/archived", headers=_admin_auth_headers())

    assert response.status_code == 200
    data = response.json()["data"]
    file_ids = {item["file_id"] for item in data["files"]}
    assert file_ids == {archived_file.file_id}
    assert data["files"][0]["download_url"]


def test_admin_archived_files_endpoint_is_admin_only() -> None:
    # AC-FV10-040: "a non-admin (including the original owner) cannot, even
    # via that same endpoint."
    auth_service = AuthService(token_service=TokenService(secret="test-secret"))
    org = auth_service.store.create_organization("Archive Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    repository.save(
        _file(
            org_id=org.org_id,
            user_id=owner_id,
            archived_at=datetime.now(timezone.utc),
        )
    )
    client: Any = TestClient(
        create_app(file_repository=repository, object_storage_adapter=storage, auth_service=auth_service)
    )

    response = client.get("/api/v2/admin/files/archived", headers=_auth_headers(owner_token))

    assert response.status_code == 403


def test_retention_sweep_runs_at_least_once_shortly_after_app_startup() -> None:
    # TC-FV10-136 / FR-FV10-050: a short interval override stands in for the
    # real 24h schedule so the test window stays bounded.
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    expired_file = _file(
        last_accessed_at=datetime.now(timezone.utc) - timedelta(days=11),
    )
    repository.save(expired_file)
    app = create_app(
        file_repository=repository,
        object_storage_adapter=storage,
        retention_sweep_interval_seconds=1000.0,
    )

    with TestClient(app):
        time.sleep(0.3)

    swept = repository.get(expired_file.file_id)
    assert swept is not None
    assert swept.archived_at is not None
