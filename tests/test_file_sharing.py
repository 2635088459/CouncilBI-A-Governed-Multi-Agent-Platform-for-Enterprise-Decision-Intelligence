from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.auth import (
    AuthService,
    PasswordHasher,
    SignUpRequest,
    TokenService,
    permissions_for_roles,
)
from chatbi.files import InMemoryFileRepository, InMemoryObjectStorageAdapter, UserUploadedFile


_PASSWORD = "correct horse battery staple"


def _fresh_auth_service() -> AuthService:
    return AuthService(token_service=TokenService(secret="test-secret"))


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


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _build_client(auth_service: AuthService) -> tuple[Any, InMemoryFileRepository]:
    repository = InMemoryFileRepository()
    app = create_app(
        file_repository=repository,
        object_storage_adapter=InMemoryObjectStorageAdapter(),
        auth_service=auth_service,
    )
    return TestClient(app), repository


def _seed_file(
    repository: InMemoryFileRepository,
    *,
    org_id: str,
    user_id: str,
    scope: str = "team",
    file_id: str = "ufile_shared00000000000000000001",
) -> UserUploadedFile:
    file_record = UserUploadedFile(
        file_id=file_id,
        org_id=org_id,
        user_id=user_id,
        original_name="forecast.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=10,
        storage_key=f"{org_id}/{user_id}/{file_id}/forecast.csv",
        content_hash=f"hash_{file_id}",
        status="ready",
        scope=scope,  # type: ignore[arg-type]
        file_group_id="fgrp_shared",
        version_number=1,
        is_latest=True,
        created_at=datetime.now(timezone.utc),
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}]},
        row_count=1,
    )
    repository.save(file_record)
    return file_record


def test_owner_can_share_file_and_grantee_can_then_access_it() -> None:
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Shared Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    colleague_id, colleague_token = _seed_user(
        auth_service, org.org_id, "colleague@example.com", "analyst"
    )
    client, repository = _build_client(auth_service)
    _seed_file(repository, org_id=org.org_id, user_id=owner_id, scope="team")

    before_share = client.get(
        "/api/v2/files/ufile_shared00000000000000000001", headers=_auth_headers(colleague_token)
    )
    share_response = client.post(
        "/api/v2/files/ufile_shared00000000000000000001/share",
        headers=_auth_headers(owner_token),
        json={"granted_to": colleague_id},
    )
    after_share = client.get(
        "/api/v2/files/ufile_shared00000000000000000001", headers=_auth_headers(colleague_token)
    )

    assert before_share.status_code == 404
    assert share_response.status_code == 201
    assert share_response.json()["data"]["granted_to"] == colleague_id
    assert after_share.status_code == 200


def test_revoking_a_share_immediately_removes_grantee_access() -> None:
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Shared Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    colleague_id, colleague_token = _seed_user(
        auth_service, org.org_id, "colleague@example.com", "analyst"
    )
    client, repository = _build_client(auth_service)
    _seed_file(repository, org_id=org.org_id, user_id=owner_id, scope="team")
    share_response = client.post(
        "/api/v2/files/ufile_shared00000000000000000001/share",
        headers=_auth_headers(owner_token),
        json={"granted_to": colleague_id},
    )
    share_id = share_response.json()["data"]["share_id"]

    revoke_response = client.delete(
        f"/api/v2/files/ufile_shared00000000000000000001/share/{share_id}",
        headers=_auth_headers(owner_token),
    )
    after_revoke = client.get(
        "/api/v2/files/ufile_shared00000000000000000001", headers=_auth_headers(colleague_token)
    )

    assert revoke_response.status_code == 204
    assert after_revoke.status_code == 404


def test_revoking_the_same_share_twice_is_idempotent() -> None:
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Shared Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    colleague_id, _colleague_token = _seed_user(
        auth_service, org.org_id, "colleague@example.com", "analyst"
    )
    client, repository = _build_client(auth_service)
    _seed_file(repository, org_id=org.org_id, user_id=owner_id, scope="team")
    share_response = client.post(
        "/api/v2/files/ufile_shared00000000000000000001/share",
        headers=_auth_headers(owner_token),
        json={"granted_to": colleague_id},
    )
    share_id = share_response.json()["data"]["share_id"]

    first_revoke = client.delete(
        f"/api/v2/files/ufile_shared00000000000000000001/share/{share_id}",
        headers=_auth_headers(owner_token),
    )
    second_revoke = client.delete(
        f"/api/v2/files/ufile_shared00000000000000000001/share/{share_id}",
        headers=_auth_headers(owner_token),
    )

    assert first_revoke.status_code == 204
    assert second_revoke.status_code == 204


def test_owner_cannot_share_to_a_user_in_a_different_org() -> None:
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Shared Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    outsider_user, _outsider_tokens = auth_service.sign_up(
        SignUpRequest(
            email="outsider@example.com",
            password=_PASSWORD,
            display_name="Outsider",
        )
    )
    client, repository = _build_client(auth_service)
    _seed_file(repository, org_id=org.org_id, user_id=owner_id, scope="team")

    response = client.post(
        "/api/v2/files/ufile_shared00000000000000000001/share",
        headers=_auth_headers(owner_token),
        json={"granted_to": outsider_user.user_id},
    )

    assert response.status_code == 422


def test_org_scoped_file_needs_no_share_record_for_analyst_in_same_org() -> None:
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Shared Org")
    owner_id, _owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    _colleague_id, colleague_token = _seed_user(
        auth_service, org.org_id, "colleague@example.com", "analyst"
    )
    client, repository = _build_client(auth_service)
    _seed_file(repository, org_id=org.org_id, user_id=owner_id, scope="org")

    response = client.get(
        "/api/v2/files/ufile_shared00000000000000000001", headers=_auth_headers(colleague_token)
    )

    assert response.status_code == 200


def test_business_user_cannot_read_org_scoped_file() -> None:
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Shared Org")
    owner_id, _owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    _biz_id, biz_token = _seed_user(
        auth_service, org.org_id, "biz@example.com", "business_user"
    )
    client, repository = _build_client(auth_service)
    _seed_file(repository, org_id=org.org_id, user_id=owner_id, scope="org")

    response = client.get(
        "/api/v2/files/ufile_shared00000000000000000001", headers=_auth_headers(biz_token)
    )

    assert response.status_code == 404
