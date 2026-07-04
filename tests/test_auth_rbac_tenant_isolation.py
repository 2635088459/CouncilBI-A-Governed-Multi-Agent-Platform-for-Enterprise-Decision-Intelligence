import base64
import json
from datetime import timedelta
from time import perf_counter
from typing import Sequence

import pytest
from fastapi.testclient import TestClient

from chatbi.auth import (
    AUTH_TABLES_SQL,
    AuthContext,
    AuthConnection,
    AuthService,
    InMemoryAuthStore,
    InvalidCredentials,
    PasswordHasher,
    PermissionDenied,
    PostgresAuthStore,
    SignUpRequest,
    TokenExpired,
    TokenService,
    permissions_for_roles,
    require_permission,
    utc_now,
)
from chatbi.api.http import _build_default_auth_service, create_app
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import Locale, UserRole
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.evaluation_repository import EvalRunRecord, EvalRunStatus, InMemoryEvaluationRepository
from chatbi.governance import InMemoryGuardrailAuditLogV2
from chatbi.history.request_metadata import InMemoryRequestMetadataStore, RequestMetadataRecord
from chatbi.history.query_results import InMemoryRuntimeQueryResultStore
from chatbi.orchestration.worker import InMemoryWorkerHandoffQueue


class FakeAuthConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.next_row: Sequence[object] | None = None
        self.next_rows: Sequence[Sequence[object]] = ()

    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        self.commands.append((sql, tuple(params)))
        return object()

    def fetchone(self) -> Sequence[object] | None:
        return self.next_row

    def fetchall(self) -> Sequence[Sequence[object]]:
        return self.next_rows

    def commit(self) -> None:
        self.commits += 1


class FakePsycopgCursor:
    def fetchone(self) -> Sequence[object] | None:
        return None

    def fetchall(self) -> Sequence[Sequence[object]]:
        return ()


class FakePsycopgConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, sql: str, params: Sequence[object] = ()) -> FakePsycopgCursor:
        self.commands.append((sql, tuple(params)))
        return FakePsycopgCursor()

    def commit(self) -> None:
        self.commits += 1


def auth_service() -> AuthService:
    return AuthService(
        store=InMemoryAuthStore(),
        password_hasher=PasswordHasher(),
        token_service=TokenService(
            secret="unit-test-secret-from-fixture",
            access_ttl_seconds=60,
            refresh_ttl_seconds=3600,
        ),
    )


def access_token_payload(access_token: str) -> dict[str, object]:
    body, _signature = access_token.split(".", 1)
    padding = "=" * (-len(body) % 4)
    decoded = base64.urlsafe_b64decode(f"{body}{padding}".encode("ascii"))
    return json.loads(decoded)


def test_postgres_auth_store_initializes_schema() -> None:
    connection: AuthConnection = FakeAuthConnection()
    store = PostgresAuthStore(connection)

    store.initialize_schema()

    fake_connection = connection
    assert isinstance(fake_connection, FakeAuthConnection)
    assert fake_connection.commands == [(AUTH_TABLES_SQL, ())]
    assert fake_connection.commits == 1


def test_create_app_wires_postgres_auth_store_only_with_auth_connect() -> None:
    raw_connection = FakePsycopgConnection()
    seen_urls: list[str] = []

    def connect(database_url: str) -> FakePsycopgConnection:
        seen_urls.append(database_url)
        return raw_connection

    create_app(
        runtime_config=RuntimeConfig(
            database_url="postgresql://chatbi:test@localhost:5432/chatbi",
            redis_url=None,
            vector_store_url=None,
        ),
        request_metadata_store=InMemoryRequestMetadataStore(),
        guardrail_audit_log_v2=InMemoryGuardrailAuditLogV2(),
        auth_connect=connect,
        use_postgres_metadata=True,
    )

    assert seen_urls == ["postgresql://chatbi:test@localhost:5432/chatbi"]
    assert raw_connection.commands == [(AUTH_TABLES_SQL, ())]
    assert raw_connection.commits == 1


def test_postgres_auth_store_creates_user_without_plaintext_password() -> None:
    connection = FakeAuthConnection()
    store = PostgresAuthStore(connection)

    org = store.create_organization("Acme")
    user = store.create_user(
        email="User@Example.com",
        password_hash="pbkdf2_sha256$210000$salt$digest",
        display_name="User",
        org_id=org.org_id,
        roles=("business_user",),
        permissions=permissions_for_roles(("business_user",)),
    )

    org_sql, org_params = connection.commands[0]
    lookup_sql, lookup_params = connection.commands[1]
    user_sql, user_params = connection.commands[2]

    assert "INSERT INTO auth.organizations" in org_sql
    assert org_params[0].startswith("org_")
    assert "FROM auth.users" in lookup_sql
    assert lookup_params == ("user@example.com",)
    assert "INSERT INTO auth.users" in user_sql
    assert user.email == "user@example.com"
    assert user_params[1] == "user@example.com"
    assert user_params[3] == "pbkdf2_sha256$210000$salt$digest"
    assert "correct horse battery staple" not in str(user_params)
    assert connection.commits == 2


def test_postgres_auth_store_loads_and_revokes_refresh_session() -> None:
    expires_at = utc_now() + timedelta(hours=1)
    connection = FakeAuthConnection()
    connection.next_row = (
        "sess_001",
        "user_001",
        "hashed_refresh",
        expires_at,
        None,
        utc_now(),
    )
    store = PostgresAuthStore(connection)

    session = store.get_refresh_session_by_token_hash("hashed_refresh")
    store.revoke_refresh_session("sess_001")

    assert session is not None
    assert session.active
    assert "FROM auth.refresh_sessions" in connection.commands[0][0]
    assert connection.commands[0][1] == ("hashed_refresh",)
    assert "UPDATE auth.refresh_sessions" in connection.commands[1][0]
    assert connection.commands[1][1][1] == "sess_001"
    assert connection.commits == 1


def test_postgres_auth_store_role_update_writes_tenant_scoped_audit() -> None:
    created_at = utc_now()
    connection = FakeAuthConnection()
    connection.next_row = (
        "user_target",
        "target@example.com",
        "Target",
        "pbkdf2_sha256$210000$salt$digest",
        "org_001",
        ["business_user"],
        permissions_for_roles(("business_user",)),
        created_at,
    )
    store = PostgresAuthStore(connection)
    admin = AuthContext(
        user_id="admin_001",
        org_id="org_001",
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        trace_id="tr_pg_auth",
    )

    updated = store.update_user_roles(
        actor=admin,
        target_user_id="user_target",
        roles=("analyst",),
        permissions=permissions_for_roles(("analyst",)),
    )

    update_sql, update_params = connection.commands[1]
    audit_sql, audit_params = connection.commands[2]
    assert updated.roles == ("analyst",)
    assert updated.token_version == 2
    assert "UPDATE auth.users" in update_sql
    assert "token_version = token_version + 1" in update_sql
    assert update_params[0] == ["analyst"]
    assert update_params[4] == "org_001"
    assert "INSERT INTO auth.role_audit_events" in audit_sql
    assert audit_params[1] == "org_001"
    assert audit_params[2] == "admin_001"
    assert audit_params[3] == "user_target"
    assert audit_params[5] == ["business_user"]
    assert audit_params[6] == ["analyst"]
    assert connection.commits == 1


def test_postgres_auth_store_rejects_cross_tenant_role_update_without_audit() -> None:
    created_at = utc_now()
    connection = FakeAuthConnection()
    connection.next_row = (
        "user_target",
        "target@example.com",
        "Target",
        "pbkdf2_sha256$210000$salt$digest",
        "org_other",
        ["business_user"],
        permissions_for_roles(("business_user",)),
        created_at,
    )
    store = PostgresAuthStore(connection)
    admin = AuthContext(
        user_id="admin_001",
        org_id="org_001",
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        trace_id="tr_pg_auth_cross_tenant",
    )

    with pytest.raises(KeyError):
        store.update_user_roles(
            actor=admin,
            target_user_id="user_target",
            roles=("analyst",),
            permissions=permissions_for_roles(("analyst",)),
        )

    assert len(connection.commands) == 1
    assert "FROM auth.users" in connection.commands[0][0]
    assert connection.commits == 0


def test_postgres_auth_store_lists_role_audit_events_by_org() -> None:
    occurred_at = utc_now()
    connection = FakeAuthConnection()
    connection.next_rows = (
        (
            "aud_001",
            "org_001",
            "admin_001",
            "user_001",
            "user.roles_updated",
            ["business_user"],
            ["analyst"],
            permissions_for_roles(("business_user",)),
            permissions_for_roles(("analyst",)),
            occurred_at,
        ),
    )
    store = PostgresAuthStore(connection)

    events = store.list_role_audit_events("org_001")

    assert len(events) == 1
    assert events[0].org_id == "org_001"
    assert events[0].roles_after == ("analyst",)
    assert "FROM auth.role_audit_events" in connection.commands[0][0]
    assert connection.commands[0][1] == ("org_001",)


def test_password_hash_rejects_plaintext_comparison_and_accepts_valid_password() -> None:
    hasher = PasswordHasher()

    password_hash = hasher.hash_password("correct horse battery staple")

    assert "correct horse battery staple" not in password_hash
    assert password_hash != "correct horse battery staple"
    assert hasher.verify_password("correct horse battery staple", password_hash)
    assert not hasher.verify_password("wrong password", password_hash)


def test_token_validation_rejects_expired_malformed_and_wrong_signature_tokens() -> None:
    token_service = TokenService(secret="token-secret", access_ttl_seconds=1)
    context = AuthContext(
        user_id="user_1",
        org_id="org_1",
        roles=("business_user",),
        permissions=permissions_for_roles(("business_user",)),
    )
    issued_at = utc_now()
    token = token_service.issue_access_token(context, now=issued_at)

    decoded = token_service.decode_access_token(token, trace_id="tr_auth")

    assert decoded.user_id == "user_1"
    assert decoded.org_id == "org_1"
    with pytest.raises(TokenExpired):
        token_service.decode_access_token(
            token,
            trace_id="tr_auth",
            now=issued_at + timedelta(seconds=2),
        )
    with pytest.raises(InvalidCredentials):
        token_service.decode_access_token("not-a-token", trace_id="tr_auth")
    with pytest.raises(InvalidCredentials):
        TokenService(secret="different-secret").decode_access_token(token, trace_id="tr_auth")


def test_access_token_payload_is_minimized_and_contains_no_credentials() -> None:
    token_service = TokenService(secret="token-secret", access_ttl_seconds=60)
    context = AuthContext(
        user_id="user_1",
        org_id="org_1",
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        token_version=7,
    )

    payload = access_token_payload(token_service.issue_access_token(context))

    assert set(payload) == {
        "typ",
        "sub",
        "org",
        "roles",
        "permissions",
        "ver",
        "iat",
        "exp",
    }
    assert payload["typ"] == "access"
    assert payload["sub"] == "user_1"
    assert payload["org"] == "org_1"
    assert payload["ver"] == 7
    assert "password" not in payload
    assert "password_hash" not in payload
    assert "refresh_token" not in payload
    assert "email" not in payload


def test_mocked_auth_access_token_validation_p95_is_under_50ms() -> None:
    service = auth_service()
    user, tokens = service.sign_up(
        SignUpRequest(
            email="auth-p95@example.com",
            password="correct horse battery staple",
            display_name="Auth P95",
            organization_name="Auth P95 Org",
        )
    )

    durations_ms: list[float] = []
    for index in range(200):
        started_at = perf_counter()
        context = service.authenticate_access_token(
            tokens.access_token,
            trace_id=f"tr_auth_p95_{index}",
        )
        durations_ms.append((perf_counter() - started_at) * 1000)
        assert context.user_id == user.user_id

    p95_ms = sorted(durations_ms)[int(len(durations_ms) * 0.95) - 1]
    assert p95_ms <= 50.0


def test_auth_token_secret_comes_from_env_or_runtime_random_secret() -> None:
    env_service = _build_default_auth_service(env={"CHATBI_AUTH_TOKEN_SECRET": "env-secret-from-test"})
    env_user, env_tokens = env_service.sign_up(
        SignUpRequest(
            email="env-secret@example.com",
            password="correct horse battery staple",
            display_name="Env Secret",
            organization_name="Env Secret Org",
        )
    )

    decoded = TokenService(secret="env-secret-from-test").decode_access_token(
        env_tokens.access_token,
        trace_id="tr_env_secret",
    )

    assert decoded.user_id == env_user.user_id
    with pytest.raises(InvalidCredentials):
        TokenService(secret="wrong-secret").decode_access_token(
            env_tokens.access_token,
            trace_id="tr_wrong_secret",
        )

    first_runtime_service = _build_default_auth_service(env={})
    second_runtime_service = _build_default_auth_service(env={})
    _runtime_user, runtime_tokens = first_runtime_service.sign_up(
        SignUpRequest(
            email="runtime-secret@example.com",
            password="correct horse battery staple",
            display_name="Runtime Secret",
            organization_name="Runtime Secret Org",
        )
    )

    with pytest.raises(InvalidCredentials):
        second_runtime_service._token_service.decode_access_token(  # noqa: SLF001
            runtime_tokens.access_token,
            trace_id="tr_runtime_secret_not_fixed",
        )


def test_signup_signin_and_refresh_rotation() -> None:
    service = auth_service()

    signed_up_user, signed_up_tokens = service.sign_up(
        SignUpRequest(
            email="Analyst@example.com",
            password="correct horse battery staple",
            display_name="Analyst",
            organization_name="Acme",
        )
    )
    signed_in_user, signed_in_tokens = service.sign_in(
        "analyst@example.com",
        "correct horse battery staple",
    )
    refreshed_user, refreshed_tokens = service.refresh(signed_in_tokens.refresh_token)

    assert signed_in_user.user_id == signed_up_user.user_id
    assert refreshed_user.user_id == signed_up_user.user_id
    assert signed_up_tokens.access_token
    assert refreshed_tokens.refresh_token != signed_in_tokens.refresh_token
    with pytest.raises(InvalidCredentials):
        service.refresh(signed_in_tokens.refresh_token)


def test_role_change_invalidates_old_access_token_and_refreshes_new_roles() -> None:
    service = auth_service()
    user, tokens = service.sign_up(
        SignUpRequest(
            email="stale-admin-token@example.com",
            password="correct horse battery staple",
            display_name="Stale Admin",
            organization_name="Acme",
        )
    )
    bootstrap_admin = AuthContext(
        user_id="bootstrap_admin",
        org_id=user.org_id,
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        trace_id="tr_token_version_bootstrap",
    )
    promoted = service.update_user_roles(
        actor=bootstrap_admin,
        target_user_id=user.user_id,
        roles=("admin",),
    )
    _signed_in_admin, admin_tokens = service.sign_in(
        "stale-admin-token@example.com",
        "correct horse battery staple",
    )
    demoted = service.update_user_roles(
        actor=AuthContext(
            user_id="bootstrap_admin",
            org_id=user.org_id,
            roles=("admin",),
            permissions=permissions_for_roles(("admin",)),
            trace_id="tr_token_version_demote",
        ),
        target_user_id=user.user_id,
        roles=("business_user",),
    )

    assert promoted.token_version == 2
    assert demoted.token_version == 3
    with pytest.raises(InvalidCredentials):
        service.authenticate_access_token(
            admin_tokens.access_token,
            trace_id="tr_stale_access_token",
        )

    refreshed_user, refreshed_tokens = service.refresh(tokens.refresh_token)
    refreshed_context = service.authenticate_access_token(
        refreshed_tokens.access_token,
        trace_id="tr_refreshed_access_token",
    )
    assert refreshed_user.roles == ("business_user",)
    assert refreshed_context.roles == ("business_user",)
    assert refreshed_context.token_version == 3


def test_rbac_permission_helper_rejects_missing_permission() -> None:
    context = AuthContext(
        user_id="user_1",
        org_id="org_1",
        roles=("business_user",),
        permissions=permissions_for_roles(("business_user",)),
    )

    require_permission(context, "chat:query")
    with pytest.raises(PermissionDenied):
        require_permission(context, "admin:trace:read")


def test_role_change_writes_tenant_scoped_audit_event() -> None:
    service = auth_service()
    target_user, _target_tokens = service.sign_up(
        SignUpRequest(
            email="target@example.com",
            password="correct horse battery staple",
            display_name="Target",
            organization_name="Acme",
        )
    )
    admin = AuthContext(
        user_id="admin_1",
        org_id=target_user.org_id,
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        trace_id="tr_role_update",
    )

    updated = service.update_user_roles(
        actor=admin,
        target_user_id=target_user.user_id,
        roles=("analyst",),
    )
    events = service.list_role_audit_events(admin)

    assert updated.roles == ("analyst",)
    assert len(events) == 1
    assert events[0].org_id == target_user.org_id
    assert events[0].actor_user_id == "admin_1"
    assert events[0].target_user_id == target_user.user_id
    assert events[0].action == "user.roles_updated"


def test_cross_tenant_role_change_is_hidden_and_not_audited() -> None:
    service = auth_service()
    tenant_a_user, _tenant_a_tokens = service.sign_up(
        SignUpRequest(
            email="tenant-a-role@example.com",
            password="correct horse battery staple",
            display_name="Tenant A",
            organization_name="Tenant A",
        )
    )
    tenant_b_user, _tenant_b_tokens = service.sign_up(
        SignUpRequest(
            email="tenant-b-role@example.com",
            password="correct horse battery staple",
            display_name="Tenant B",
            organization_name="Tenant B",
        )
    )
    tenant_a_admin = AuthContext(
        user_id="admin_tenant_a",
        org_id=tenant_a_user.org_id,
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        trace_id="tr_cross_tenant_role",
    )

    with pytest.raises(KeyError):
        service.update_user_roles(
            actor=tenant_a_admin,
            target_user_id=tenant_b_user.user_id,
            roles=("admin",),
        )

    assert service.store.get_user(tenant_b_user.user_id).roles == ("business_user",)
    assert service.list_role_audit_events(tenant_a_admin) == ()


def signup(client: TestClient, email: str, password: str = "correct horse battery staple") -> dict:
    response = client.post(
        "/api/v2/auth/signup",
        json={
            "email": email,
            "password": password,
            "display_name": email.split("@", 1)[0],
            "organization_name": f"Org {email}",
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def valid_document_body(document_id: str = "doc_auth_scope_001") -> dict[str, object]:
    return {
        "document_id": document_id,
        "source": "release-notes",
        "title": "June Release Notes",
        "document_type": "release_note",
        "published_at": "2026-06-29T10:00:00Z",
        "business_tags": ["revenue", "release"],
        "permission_tags": ["admin"],
        "text": "Revenue dashboard drill-down filters were improved.",
    }


def valid_analytics_body(trace_id: str = "tr_auth_analytics") -> dict[str, object]:
    return {
        "trace_id": trace_id,
        "metric_id": "revenue",
        "semantic_version_id": "sem_v2",
        "time_column": "date",
        "value_column": "revenue",
        "grain": "day",
        "rows": [
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
            {"date": "2026-06-03", "revenue": 110.0},
            {"date": "2026-06-04", "revenue": 120.0},
        ],
        "analysis_options": {"horizon": 2, "anomaly_z_threshold": 3.0},
    }


def assert_response_omits_values(response_text: str, forbidden_values: tuple[str, ...]) -> None:
    for forbidden_value in forbidden_values:
        assert forbidden_value not in response_text


def promote_signup_to_admin(
    service: AuthService,
    client: TestClient,
    email: str,
) -> tuple[dict, str]:
    user_data = signup(client, email)
    admin_context = AuthContext(
        user_id="bootstrap_admin",
        org_id=user_data["user"]["org_id"],
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        trace_id="tr_bootstrap_admin",
    )
    service.store.update_user_roles(
        actor=admin_context,
        target_user_id=user_data["user"]["user_id"],
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
    )
    _admin_user, admin_tokens = service.sign_in(email, "correct horse battery staple")
    return user_data, admin_tokens.access_token


def test_signup_signin_and_call_authenticated_chat_endpoint() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))

    signup_data = signup(client, "chat-user@example.com")
    signin_response = client.post(
        "/api/v2/auth/signin",
        json={
            "email": "chat-user@example.com",
            "password": "correct horse battery staple",
        },
    )
    access_token = signin_response.json()["data"]["tokens"]["access_token"]
    user_id = signup_data["user"]["user_id"]

    response = client.post(
        "/api/v2/chat/query",
        headers=bearer(access_token),
        json={
            "request_id": "req_auth_chat_001",
            "session_id": "ses_auth_chat_001",
            "user_id": user_id,
            "role": "business_user",
            "locale": "en",
            "question": "Show revenue trend.",
        },
    )

    assert signin_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["data"]["answer_text"] == "Revenue trend is ready."


def test_http_refresh_rotation_rejects_old_refresh_token_without_echo() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    signup_data = signup(client, "http-refresh-rotation@example.com")
    old_refresh_token = signup_data["tokens"]["refresh_token"]

    refresh_response = client.post(
        "/api/v2/auth/refresh",
        json={"refresh_token": old_refresh_token},
    )
    reuse_response = client.post(
        "/api/v2/auth/refresh",
        json={"refresh_token": old_refresh_token},
    )
    new_refresh_token = refresh_response.json()["data"]["tokens"]["refresh_token"]

    assert refresh_response.status_code == 200
    assert new_refresh_token != old_refresh_token
    assert reuse_response.status_code == 401
    assert reuse_response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert old_refresh_token not in reuse_response.text


def test_http_refresh_session_revoke_is_idempotent_and_does_not_echo_token() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    signup_data = signup(client, "http-refresh-revoke@example.com")
    refresh_token = signup_data["tokens"]["refresh_token"]
    missing_refresh_token = "rfr_missing_plaintext_should_not_echo"

    revoke_response = client.post(
        "/api/v2/auth/sessions/revoke",
        json={"refresh_token": refresh_token},
    )
    refresh_after_revoke = client.post(
        "/api/v2/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    missing_revoke_response = client.post(
        "/api/v2/auth/sessions/revoke",
        json={"refresh_token": missing_refresh_token},
    )

    assert revoke_response.status_code == 200
    assert revoke_response.json()["data"] == {"revoked": True}
    assert refresh_after_revoke.status_code == 401
    assert refresh_after_revoke.json()["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert missing_revoke_response.status_code == 200
    assert missing_revoke_response.json()["data"] == {"revoked": True}
    assert refresh_token not in revoke_response.text
    assert refresh_token not in refresh_after_revoke.text
    assert missing_refresh_token not in missing_revoke_response.text


def test_auth_error_responses_do_not_echo_passwords_or_tokens() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    signup(client, "auth-error-redaction@example.com")
    wrong_password = "wrong password should not echo"
    invalid_refresh_token = "rfr_plaintext_should_not_echo"
    invalid_access_token = "invalid.access.token.should.not.echo"
    short_password = "short"

    signin_response = client.post(
        "/api/v2/auth/signin",
        json={
            "email": "auth-error-redaction@example.com",
            "password": wrong_password,
        },
    )
    refresh_response = client.post(
        "/api/v2/auth/refresh",
        json={"refresh_token": invalid_refresh_token},
    )
    bearer_response = client.get(
        "/api/v2/release-gates/latest",
        headers=bearer(invalid_access_token),
    )
    signup_response = client.post(
        "/api/v2/auth/signup",
        json={
            "email": "short-password@example.com",
            "password": short_password,
            "display_name": "Short Password",
            "organization_name": "Short Password Org",
        },
    )

    assert signin_response.status_code == 401
    assert refresh_response.status_code == 401
    assert bearer_response.status_code == 401
    assert signup_response.status_code == 400
    assert signin_response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert refresh_response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert bearer_response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"
    assert_response_omits_values(
        signin_response.text,
        ("auth-error-redaction@example.com", wrong_password),
    )
    assert_response_omits_values(refresh_response.text, (invalid_refresh_token,))
    assert_response_omits_values(bearer_response.text, (invalid_access_token,))
    assert_response_omits_values(signup_response.text, (short_password,))


def test_business_user_receives_403_from_admin_trace_endpoint() -> None:
    service = auth_service()
    query_result_store = InMemoryRuntimeQueryResultStore()
    client = TestClient(
        create_app(auth_service=service, runtime_query_result_store=query_result_store)
    )
    user = signup(client, "business-trace@example.com")
    token = user["tokens"]["access_token"]

    query_response = client.post(
        "/api/v2/chat/query",
        headers=bearer(token),
        json={
            "request_id": "req_trace_forbidden_001",
            "session_id": "ses_trace_forbidden_001",
            "user_id": user["user"]["user_id"],
            "role": "business_user",
            "locale": "en",
            "question": "Show revenue trend.",
        },
    )
    trace_id = query_response.json()["trace_id"]

    response = client.get(f"/api/v2/governance/traces/{trace_id}", headers=bearer(token))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTH_FORBIDDEN"


def test_business_user_receives_403_from_admin_eval_release_and_document_endpoints() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    user = signup(client, "business-admin-surfaces@example.com")
    headers = bearer(user["tokens"]["access_token"])

    eval_response = client.post(
        "/api/v2/evals/run",
        headers=headers,
        json={"eval_suite_id": "backend_api_smoke", "questions": ["Show revenue trend."]},
    )
    release_response = client.get("/api/v2/release-gates/latest", headers=headers)
    admin_summary_response = client.get(
        "/api/v2/admin/observability/summary",
        headers=headers,
    )
    document_response = client.post(
        "/api/v2/documents/index",
        headers=headers,
        json=valid_document_body(),
    )

    assert eval_response.status_code == 403
    assert release_response.status_code == 403
    assert admin_summary_response.status_code == 403
    assert document_response.status_code == 403
    assert eval_response.json()["error"]["code"] == "AUTH_FORBIDDEN"
    assert release_response.json()["error"]["code"] == "AUTH_FORBIDDEN"
    assert admin_summary_response.json()["error"]["code"] == "AUTH_FORBIDDEN"
    assert document_response.json()["error"]["code"] == "AUTH_FORBIDDEN"


def test_admin_observability_summary_returns_contract_and_audits_admin_read() -> None:
    service = auth_service()
    application = ChatBIApplication()
    client = TestClient(create_app(application=application, auth_service=service))
    admin_data, admin_token = promote_signup_to_admin(
        service,
        client,
        "admin-observability-summary@example.com",
    )
    headers = bearer(admin_token)
    client.post(
        "/api/v2/evals/run",
        headers=headers,
        json={
            "eval_suite_id": "backend_api_smoke",
            "questions": ["Show revenue trend."],
            "locale": "en",
            "role": "analyst",
        },
    )

    response = client.get("/api/v2/admin/observability/summary", headers=headers)

    body = response.json()
    data = body["data"]
    assert response.status_code == 200
    assert set(data) == {
        "system_health",
        "llm_health",
        "sql_safety",
        "rag_health",
        "eval_summary",
        "release_gate",
        "audit_summary",
    }
    assert data["system_health"]["service"] == "chatbi-api"
    assert data["llm_health"]["provider"] == "mock"
    assert data["rag_health"]["embedding_provider"] == "mock"
    assert data["eval_summary"]["eval_suite_id"] == "backend_api_smoke"
    assert data["release_gate"]["release_gate_passed"] is True
    assert data["audit_summary"]["admin_observability_read_count"] == 1
    assert any(
        record.endpoint == "/api/v2/admin/observability/summary"
        and record.user_id == admin_data["user"]["user_id"]
        for record in application.audit_records
    )


def test_admin_observability_summary_is_tenant_scoped() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    tenant_a, admin_a_token = promote_signup_to_admin(
        service,
        client,
        "admin-observability-tenant-a@example.com",
    )
    _tenant_b, admin_b_token = promote_signup_to_admin(
        service,
        client,
        "admin-observability-tenant-b@example.com",
    )
    client.post(
        "/api/v2/chat/query",
        headers=bearer(admin_a_token),
        json={
            "request_id": "req_admin_obs_tenant_a",
            "session_id": "ses_admin_obs_tenant_a",
            "user_id": tenant_a["user"]["user_id"],
            "role": "admin",
            "locale": "en",
            "question": "Show revenue trend.",
        },
    )
    client.post(
        "/api/v2/evals/run",
        headers=bearer(admin_a_token),
        json={
            "eval_suite_id": "tenant_a_eval",
            "questions": ["Show revenue trend."],
            "locale": "en",
            "role": "analyst",
        },
    )

    response = client.get(
        "/api/v2/admin/observability/summary",
        headers=bearer(admin_b_token),
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["system_health"]["request_count"] == 0
    assert data["eval_summary"]["status"] == "not_run"
    assert data["eval_summary"]["latest_eval_run_id"] is None
    assert data["audit_summary"]["admin_observability_read_count"] == 1
    assert "tenant_a_eval" not in response.text
    assert tenant_a["user"]["user_id"] not in response.text


def test_admin_observability_summary_surfaces_failed_release_gate_blocker() -> None:
    service = auth_service()
    evaluation_repository = InMemoryEvaluationRepository()
    client = TestClient(
        create_app(
            auth_service=service,
            application=ChatBIApplication(evaluation_repository=evaluation_repository),
        )
    )
    admin_data, admin_token = promote_signup_to_admin(
        service,
        client,
        "admin-observability-release-block@example.com",
    )
    headers = bearer(admin_token)
    evaluation_repository.save_run(
        EvalRunRecord(
            eval_run_id="eval_release_blocked",
            eval_suite_id="release_blocking_eval",
            status=EvalRunStatus.SUCCEEDED,
            started_at=utc_now(),
            finished_at=utc_now(),
            total_cases=1,
            passed_cases=0,
            failed_cases=1,
            sql_safety_score=1.0,
            release_gate_passed=False,
            org_id=admin_data["user"]["org_id"],
        )
    )

    response = client.get("/api/v2/admin/observability/summary", headers=headers)

    release_gate = response.json()["data"]["release_gate"]
    assert response.status_code == 200
    assert release_gate["release_gate_passed"] is False
    assert release_gate["blocking"] is True
    assert release_gate["failed_cases"] == 1
    assert release_gate["blocking_reason"] == (
        "Release blocked because latest eval run failed 1 case(s)."
    )
    assert release_gate["eval_report_path"] == "/api/v2/evals/eval_release_blocked"


def test_admin_observability_summary_p95_under_budget_with_ten_thousand_mock_events() -> None:
    service = auth_service()
    request_metadata_store = InMemoryRequestMetadataStore()
    client = TestClient(
        create_app(
            auth_service=service,
            request_metadata_store=request_metadata_store,
        )
    )
    admin_data, admin_token = promote_signup_to_admin(
        service,
        client,
        "admin-observability-benchmark@example.com",
    )
    org_id = admin_data["user"]["org_id"]
    for index in range(10_000):
        request_metadata_store.save_accepted(
            RequestMetadataRecord(
                trace_id=f"tr_admin_obs_benchmark_{index:05d}",
                request_id=f"req_admin_obs_benchmark_{index:05d}",
                session_id="ses_admin_obs_benchmark",
                user_id=admin_data["user"]["user_id"],
                role=UserRole.ADMIN,
                locale=Locale.EN,
                question="Show revenue trend.",
                org_id=org_id,
            )
        )

    latencies_ms: list[float] = []
    for _ in range(20):
        started_at = perf_counter()
        response = client.get(
            "/api/v2/admin/observability/summary",
            headers=bearer(admin_token),
        )
        latencies_ms.append((perf_counter() - started_at) * 1000)
        assert response.status_code == 200
        assert response.json()["data"]["system_health"]["request_count"] == 10_000

    ordered = sorted(latencies_ms)
    p95_ms = ordered[int((len(ordered) - 1) * 0.95)]
    assert p95_ms <= 500.0


def test_admin_can_run_eval_read_report_and_latest_release_gate() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    _admin_data, admin_token = promote_signup_to_admin(
        service,
        client,
        "admin-eval@example.com",
    )
    headers = bearer(admin_token)

    run_response = client.post(
        "/api/v2/evals/run",
        headers=headers,
        json={
            "eval_suite_id": "backend_api_smoke",
            "questions": ["Show revenue trend."],
            "locale": "en",
            "role": "analyst",
        },
    )
    eval_run_id = run_response.json()["data"]["eval_run_id"]
    report_response = client.get(f"/api/v2/evals/{eval_run_id}", headers=headers)
    release_response = client.get("/api/v2/release-gates/latest", headers=headers)

    assert run_response.status_code == 200
    assert run_response.json()["data"]["release_gate_passed"] is True
    assert report_response.status_code == 200
    assert report_response.json()["data"]["eval_run_id"] == eval_run_id
    assert release_response.status_code == 200
    assert release_response.json()["data"]["eval_run_id"] == eval_run_id
    assert release_response.json()["data"]["release_gate_passed"] is True


def test_tenant_admin_cannot_read_other_tenant_eval_or_release_gate() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    _tenant_a, admin_a_token = promote_signup_to_admin(
        service,
        client,
        "admin-eval-tenant-a@example.com",
    )
    _tenant_b, admin_b_token = promote_signup_to_admin(
        service,
        client,
        "admin-eval-tenant-b@example.com",
    )

    run_response = client.post(
        "/api/v2/evals/run",
        headers=bearer(admin_a_token),
        json={
            "eval_suite_id": "backend_api_smoke",
            "questions": ["Show revenue trend."],
            "locale": "en",
            "role": "analyst",
        },
    )
    eval_run_id = run_response.json()["data"]["eval_run_id"]
    tenant_b_report = client.get(
        f"/api/v2/evals/{eval_run_id}",
        headers=bearer(admin_b_token),
    )
    tenant_b_release_gate = client.get(
        "/api/v2/release-gates/latest",
        headers=bearer(admin_b_token),
    )

    assert run_response.status_code == 200
    assert tenant_b_report.status_code == 404
    assert tenant_b_report.json()["error"]["code"] == "EVAL_RUN_NOT_FOUND"
    assert tenant_b_release_gate.status_code == 200
    assert tenant_b_release_gate.json()["data"] == {"release_gate": None}


def test_document_index_payload_is_tenant_scoped_and_idempotency_is_per_tenant() -> None:
    service = auth_service()
    queue = InMemoryWorkerHandoffQueue()
    client = TestClient(create_app(auth_service=service, worker_handoff_queue=queue))
    tenant_a, admin_a_token = promote_signup_to_admin(service, client, "doc-admin-a@example.com")
    tenant_b, admin_b_token = promote_signup_to_admin(service, client, "doc-admin-b@example.com")

    response_a = client.post(
        "/api/v2/documents/index",
        headers={**bearer(admin_a_token), "Idempotency-Key": "idem_shared_document"},
        json=valid_document_body("doc_shared_idem"),
    )
    response_b = client.post(
        "/api/v2/documents/index",
        headers={**bearer(admin_b_token), "Idempotency-Key": "idem_shared_document"},
        json=valid_document_body("doc_shared_idem"),
    )

    task_a = queue.get(response_a.json()["data"]["task_id"])
    task_b = queue.get(response_b.json()["data"]["task_id"])
    assert response_a.status_code == 202
    assert response_b.status_code == 202
    assert response_a.json()["data"]["task_id"] != response_b.json()["data"]["task_id"]
    assert task_a is not None
    assert task_b is not None
    assert task_a.payload["org_id"] == tenant_a["user"]["org_id"]
    assert task_b.payload["org_id"] == tenant_b["user"]["org_id"]


def test_tenant_cannot_read_other_tenant_async_task_status() -> None:
    service = auth_service()
    queue = InMemoryWorkerHandoffQueue()
    client = TestClient(create_app(auth_service=service, worker_handoff_queue=queue))
    _tenant_a, admin_a_token = promote_signup_to_admin(service, client, "task-admin-a@example.com")
    _tenant_b, admin_b_token = promote_signup_to_admin(service, client, "task-admin-b@example.com")

    create_response = client.post(
        "/api/v2/documents/index",
        headers=bearer(admin_a_token),
        json=valid_document_body("doc_task_private"),
    )
    task_id = create_response.json()["data"]["task_id"]
    owner_lookup = client.get(
        f"/api/v2/chat/tasks/{task_id}",
        headers=bearer(admin_a_token),
    )
    other_tenant_lookup = client.get(
        f"/api/v2/chat/tasks/{task_id}",
        headers=bearer(admin_b_token),
    )

    assert create_response.status_code == 202
    assert owner_lookup.status_code == 200
    assert owner_lookup.json()["data"]["payload"]["document_id"] == "doc_task_private"
    assert other_tenant_lookup.status_code == 404
    assert other_tenant_lookup.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert "doc_task_private" not in other_tenant_lookup.text


def test_business_user_receives_403_from_v1_admin_surfaces_with_real_token() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    user = signup(client, "business-v1-admin@example.com")
    headers = {
        **bearer(user["tokens"]["access_token"]),
        "X-Trace-Id": "tr_v1_admin_forbidden",
    }

    eval_response = client.post(
        "/api/v1/evals/run?user_id=spoofed_admin",
        headers=headers,
        json={"eval_suite_id": "backend_api_smoke", "questions": ["Show revenue trend."]},
    )
    quality_response = client.get(
        "/api/v1/quality/dashboard?user_id=spoofed_admin",
        headers=headers,
    )
    document_response = client.post(
        "/api/v1/documents/index?user_id=spoofed_admin",
        headers=headers,
        json=valid_document_body("doc_v1_forbidden"),
    )
    audit_response = client.get(
        "/api/v1/audit/tr_v1_forbidden?user_id=spoofed_admin",
        headers=headers,
    )

    assert eval_response.status_code == 403
    assert quality_response.status_code == 403
    assert document_response.status_code == 403
    assert audit_response.status_code == 403
    assert eval_response.json()["code"] == "AUTH_FORBIDDEN"
    assert quality_response.json()["code"] == "AUTH_FORBIDDEN"
    assert document_response.json()["code"] == "AUTH_FORBIDDEN"
    assert audit_response.json()["code"] == "AUTH_FORBIDDEN"


def test_admin_real_token_can_use_v1_eval_and_document_index_with_org_payload() -> None:
    service = auth_service()
    queue = InMemoryWorkerHandoffQueue()
    client = TestClient(
        create_app(auth_service=service, worker_handoff_queue=queue)
    )
    admin_data, admin_token = promote_signup_to_admin(
        service,
        client,
        "admin-v1-surfaces@example.com",
    )
    headers = {
        **bearer(admin_token),
        "X-Trace-Id": "tr_v1_admin_allowed",
        "Idempotency-Key": "idem_v1_admin_doc",
    }

    eval_response = client.post(
        "/api/v1/evals/run?user_id=spoofed_user",
        headers=headers,
        json={
            "eval_suite_id": "backend_api_smoke",
            "questions": ["Show revenue trend."],
            "locale": "en",
            "role": "analyst",
        },
    )
    document_response = client.post(
        "/api/v1/documents/index?user_id=spoofed_user",
        headers=headers,
        json=valid_document_body("doc_v1_admin_allowed"),
    )
    task = queue.get(document_response.json()["data"]["task_id"])

    assert eval_response.status_code == 200
    assert document_response.status_code == 202
    assert task is not None
    assert task.payload["org_id"] == admin_data["user"]["org_id"]


def test_tenant_a_cannot_read_tenant_b_request_or_query_result() -> None:
    service = auth_service()
    query_result_store = InMemoryRuntimeQueryResultStore()
    client = TestClient(
        create_app(auth_service=service, runtime_query_result_store=query_result_store)
    )
    tenant_a = signup(client, "tenant-a@example.com")
    tenant_b = signup(client, "tenant-b@example.com")

    query_response = client.post(
        "/api/v2/chat/query",
        headers=bearer(tenant_b["tokens"]["access_token"]),
        json={
            "request_id": "req_tenant_b_001",
            "session_id": "ses_tenant_b_001",
            "user_id": tenant_b["user"]["user_id"],
            "role": "business_user",
            "locale": "en",
            "question": "Show revenue trend.",
        },
    )
    trace_id = query_response.json()["trace_id"]

    request_lookup = client.get(
        f"/api/v2/requests/{trace_id}",
        headers=bearer(tenant_a["tokens"]["access_token"]),
    )
    query_result_lookup = client.get(
        f"/api/v2/query-results/{trace_id}",
        headers=bearer(tenant_a["tokens"]["access_token"]),
    )

    assert request_lookup.status_code == 404
    assert query_result_lookup.status_code == 404
    assert "tenant-b" not in request_lookup.text
    assert "tenant-b" not in query_result_lookup.text


def test_chat_history_uses_token_user_not_client_supplied_user_id() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    tenant_a = signup(client, "history-tenant-a@example.com")
    tenant_b = signup(client, "history-tenant-b@example.com")

    tenant_b_query = client.post(
        "/api/v2/chat/query",
        headers=bearer(tenant_b["tokens"]["access_token"]),
        json={
            "request_id": "req_history_tenant_b",
            "session_id": "ses_history_tenant_b",
            "user_id": tenant_b["user"]["user_id"],
            "role": "business_user",
            "locale": "en",
            "question": "Show order count.",
        },
    )
    spoofed_history = client.get(
        "/api/v2/chat/history",
        headers=bearer(tenant_a["tokens"]["access_token"]),
        params={
            "user_id": tenant_b["user"]["user_id"],
            "page_size": 20,
        },
    )

    assert tenant_b_query.status_code == 200
    assert spoofed_history.status_code == 200
    assert spoofed_history.json()["data"]["items"] == []
    assert tenant_b["user"]["user_id"] not in spoofed_history.text
    assert "Show order count." not in spoofed_history.text


def test_query_detail_uses_token_user_not_client_supplied_user_id() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    tenant_a = signup(client, "query-detail-tenant-a@example.com")
    tenant_b = signup(client, "query-detail-tenant-b@example.com")

    tenant_b_query = client.post(
        "/api/v2/chat/query",
        headers=bearer(tenant_b["tokens"]["access_token"]),
        json={
            "request_id": "req_query_detail_tenant_b",
            "session_id": "ses_query_detail_tenant_b",
            "user_id": tenant_b["user"]["user_id"],
            "role": "business_user",
            "locale": "en",
            "question": "Show order count.",
        },
    )
    public_trace_id = tenant_b_query.json()["trace_id"]
    spoofed_detail = client.get(
        f"/api/v2/query/{public_trace_id}",
        headers=bearer(tenant_a["tokens"]["access_token"]),
        params={"user_id": tenant_b["user"]["user_id"]},
    )

    assert tenant_b_query.status_code == 200
    assert spoofed_detail.status_code == 404
    assert spoofed_detail.json()["error"]["code"] == "QUERY_NOT_FOUND"
    assert tenant_b["user"]["user_id"] not in spoofed_detail.text
    assert "Show order count." not in spoofed_detail.text


def test_tenant_cannot_read_other_tenant_analytics_result() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    _tenant_a, admin_a_token = promote_signup_to_admin(
        service,
        client,
        "analytics-admin-a@example.com",
    )
    _tenant_b, admin_b_token = promote_signup_to_admin(
        service,
        client,
        "analytics-admin-b@example.com",
    )

    analyze_response = client.post(
        "/api/v2/analytics/analyze",
        headers=bearer(admin_a_token),
        json=valid_analytics_body("tr_analytics_private_a"),
    )
    owner_lookup = client.get(
        "/api/v2/analytics/results/tr_analytics_private_a",
        headers=bearer(admin_a_token),
    )
    other_tenant_lookup = client.get(
        "/api/v2/analytics/results/tr_analytics_private_a",
        headers=bearer(admin_b_token),
    )

    assert analyze_response.status_code == 200
    assert owner_lookup.status_code == 200
    assert owner_lookup.json()["data"]["parameters"]["org_id"]
    assert other_tenant_lookup.status_code == 404
    assert other_tenant_lookup.json()["error"]["code"] == "ANALYTICS_RESULT_NOT_FOUND"
    assert "rolling_zscore_linear_forecast" not in other_tenant_lookup.text


def test_role_change_http_creates_admin_visible_audit_event() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    target = signup(client, "role-target@example.com")
    admin_context = AuthContext(
        user_id="admin_1",
        org_id=target["user"]["org_id"],
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        trace_id="tr_admin_seed",
    )
    service.store.update_user_roles(
        actor=admin_context,
        target_user_id=target["user"]["user_id"],
        roles=("business_user", "admin"),
        permissions=permissions_for_roles(("business_user", "admin")),
    )
    _admin_user, admin_tokens = service.sign_in(
        "role-target@example.com",
        "correct horse battery staple",
    )

    update_response = client.put(
        f"/api/v2/admin/users/{target['user']['user_id']}/roles",
        headers=bearer(admin_tokens.access_token),
        json={"roles": ["admin"]},
    )
    stale_audit_response = client.get(
        "/api/v2/admin/audits/roles",
        headers=bearer(admin_tokens.access_token),
    )
    _fresh_admin_user, fresh_admin_tokens = service.sign_in(
        "role-target@example.com",
        "correct horse battery staple",
    )
    audit_response = client.get(
        "/api/v2/admin/audits/roles",
        headers=bearer(fresh_admin_tokens.access_token),
    )

    assert update_response.status_code == 200
    assert stale_audit_response.status_code == 401
    assert audit_response.status_code == 200
    assert audit_response.json()["data"]["count"] >= 2
    assert audit_response.json()["data"]["items"][-1]["action"] == "user.roles_updated"


def test_admin_role_update_hides_cross_tenant_target_user() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    tenant_a, admin_a_token = promote_signup_to_admin(
        service,
        client,
        "role-admin-tenant-a@example.com",
    )
    tenant_b = signup(client, "role-target-tenant-b@example.com")

    response = client.put(
        f"/api/v2/admin/users/{tenant_b['user']['user_id']}/roles",
        headers=bearer(admin_a_token),
        json={"roles": ["admin"]},
    )
    audit_response = client.get(
        "/api/v2/admin/audits/roles",
        headers=bearer(admin_a_token),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"
    assert tenant_b["user"]["user_id"] not in response.text
    assert tenant_b["user"]["org_id"] not in response.text
    assert audit_response.status_code == 200
    assert all(
        item["target_user_id"] != tenant_b["user"]["user_id"]
        for item in audit_response.json()["data"]["items"]
    )
    assert tenant_a["user"]["org_id"] != tenant_b["user"]["org_id"]


def test_old_admin_access_token_is_rejected_after_role_demotion() -> None:
    service = auth_service()
    client = TestClient(create_app(auth_service=service))
    admin_data, admin_token = promote_signup_to_admin(
        service,
        client,
        "demoted-admin-token@example.com",
    )

    allowed_before = client.get(
        "/api/v2/release-gates/latest",
        headers=bearer(admin_token),
    )
    service.update_user_roles(
        actor=AuthContext(
            user_id="bootstrap_admin",
            org_id=admin_data["user"]["org_id"],
            roles=("admin",),
            permissions=permissions_for_roles(("admin",)),
            trace_id="tr_http_token_demotion",
        ),
        target_user_id=admin_data["user"]["user_id"],
        roles=("business_user",),
    )
    stale_response = client.get(
        "/api/v2/release-gates/latest",
        headers=bearer(admin_token),
    )

    assert allowed_before.status_code == 200
    assert stale_response.status_code == 401
    assert stale_response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"
