"""Authentication, RBAC, and tenant context for the final-version API."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib
import json
import os
import secrets
from typing import Any, Mapping, Protocol, Sequence, cast


DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 15 * 60
DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 14 * 24 * 60 * 60


AUTH_ORGANIZATIONS_TABLE = "auth.organizations"
AUTH_USERS_TABLE = "auth.users"
AUTH_REFRESH_SESSIONS_TABLE = "auth.refresh_sessions"
AUTH_ROLE_AUDIT_EVENTS_TABLE = "auth.role_audit_events"

AUTH_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.organizations (
    org_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_organizations_name
    ON auth.organizations (LOWER(name));

CREATE TABLE IF NOT EXISTS auth.users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    org_id TEXT NOT NULL REFERENCES auth.organizations(org_id),
    roles TEXT[] NOT NULL DEFAULT '{}',
    permissions TEXT[] NOT NULL DEFAULT '{}',
    token_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE auth.users
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 1;
CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_email
    ON auth.users (LOWER(email));
CREATE INDEX IF NOT EXISTS idx_auth_users_org_id
    ON auth.users (org_id);

CREATE TABLE IF NOT EXISTS auth.refresh_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES auth.users(user_id),
    refresh_token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_sessions_user_active
    ON auth.refresh_sessions (user_id, revoked_at, expires_at);

CREATE TABLE IF NOT EXISTS auth.role_audit_events (
    audit_event_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES auth.organizations(org_id),
    actor_user_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL REFERENCES auth.users(user_id),
    action TEXT NOT NULL,
    roles_before TEXT[] NOT NULL DEFAULT '{}',
    roles_after TEXT[] NOT NULL DEFAULT '{}',
    permissions_before TEXT[] NOT NULL DEFAULT '{}',
    permissions_after TEXT[] NOT NULL DEFAULT '{}',
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_role_audit_events_org_time
    ON auth.role_audit_events (org_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_role_audit_events_target
    ON auth.role_audit_events (target_user_id, occurred_at DESC);
""".strip()


class AuthError(Exception):
    """Base class for authentication failures."""


class InvalidCredentials(AuthError):
    """Raised when credentials or tokens cannot authenticate a user."""


class TokenExpired(AuthError):
    """Raised when a token is well-formed but expired."""


class PermissionDenied(Exception):
    """Raised when an authenticated user lacks a required permission."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _empty_roles() -> tuple[str, ...]:
    return ()


def _empty_permissions() -> tuple[str, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: str
    org_id: str
    roles: tuple[str, ...] = field(default_factory=_empty_roles)
    permissions: tuple[str, ...] = field(default_factory=_empty_permissions)
    trace_id: str = ""
    token_version: int = 1

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def is_admin(self) -> bool:
        return "admin" in self.roles


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    email: str
    display_name: str
    password_hash: str
    org_id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    token_version: int = 1
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class OrganizationRecord:
    org_id: str
    name: str
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class RefreshSessionRecord:
    session_id: str
    user_id: str
    refresh_token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    @property
    def active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utc_now()


@dataclass(frozen=True, slots=True)
class RoleAuditEvent:
    audit_event_id: str
    org_id: str
    actor_user_id: str
    target_user_id: str
    action: str
    roles_before: tuple[str, ...]
    roles_after: tuple[str, ...]
    permissions_before: tuple[str, ...]
    permissions_after: tuple[str, ...]
    occurred_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AuthTokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


@dataclass(frozen=True, slots=True)
class SignUpRequest:
    email: str
    password: str
    display_name: str
    organization_name: str | None = None


class AuthStore(Protocol):
    def create_organization(self, name: str) -> OrganizationRecord:
        ...

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        org_id: str,
        roles: Sequence[str],
        permissions: Sequence[str],
    ) -> UserRecord:
        ...

    def get_user_by_email(self, email: str) -> UserRecord | None:
        ...

    def get_user(self, user_id: str) -> UserRecord | None:
        ...

    def update_user_roles(
        self,
        *,
        actor: AuthContext,
        target_user_id: str,
        roles: Sequence[str],
        permissions: Sequence[str],
    ) -> UserRecord:
        ...

    def create_refresh_session(
        self,
        *,
        user_id: str,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> RefreshSessionRecord:
        ...

    def get_refresh_session_by_token_hash(
        self,
        refresh_token_hash: str,
    ) -> RefreshSessionRecord | None:
        ...

    def revoke_refresh_session(self, session_id: str) -> None:
        ...

    def list_role_audit_events(self, org_id: str) -> tuple[RoleAuditEvent, ...]:
        ...


class AuthConnection(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        ...

    def fetchone(self) -> Sequence[object] | None:
        ...

    def fetchall(self) -> Sequence[Sequence[object]]:
        ...

    def commit(self) -> None:
        ...


class PsycopgAuthConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._latest_cursor: Any | None = None

    def execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        self._latest_cursor = self._connection.execute(sql, params)
        return self._latest_cursor

    def fetchone(self) -> Sequence[object] | None:
        if self._latest_cursor is None:
            return None
        row = self._latest_cursor.fetchone()
        return cast(Sequence[object] | None, row)

    def fetchall(self) -> Sequence[Sequence[object]]:
        if self._latest_cursor is None:
            return ()
        fetchall = getattr(self._latest_cursor, "fetchall", None)
        if not callable(fetchall):
            return ()
        return cast(Sequence[Sequence[object]], fetchall())

    def commit(self) -> None:
        self._connection.commit()


class PasswordHasher:
    """PBKDF2 password hashing without storing plaintext passwords."""

    def hash_password(self, password: str) -> str:
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
        return "pbkdf2_sha256$210000${salt}${digest}".format(
            salt=base64.urlsafe_b64encode(salt).decode("ascii"),
            digest=base64.urlsafe_b64encode(digest).decode("ascii"),
        )

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            algorithm, rounds_text, salt_text, expected_text = password_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            rounds = int(rounds_text)
            salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
            expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
        except (ValueError, TypeError):
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
        return hmac.compare_digest(actual, expected)


class TokenService:
    """Small signed-token service with expiry and signature validation."""

    def __init__(
        self,
        secret: str | None = None,
        access_ttl_seconds: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
        refresh_ttl_seconds: int = DEFAULT_REFRESH_TOKEN_TTL_SECONDS,
    ) -> None:
        active_secret = secret or os.environ.get("CHATBI_AUTH_TOKEN_SECRET")
        if active_secret is None or not active_secret.strip():
            raise RuntimeError("CHATBI_AUTH_TOKEN_SECRET must be configured.")
        self._secret = active_secret.encode("utf-8")
        self._access_ttl_seconds = access_ttl_seconds
        self._refresh_ttl_seconds = refresh_ttl_seconds

    @property
    def access_ttl_seconds(self) -> int:
        return self._access_ttl_seconds

    @property
    def refresh_ttl_seconds(self) -> int:
        return self._refresh_ttl_seconds

    def issue_access_token(self, context: AuthContext, now: datetime | None = None) -> str:
        issued_at = now or utc_now()
        return self._encode(
            {
                "typ": "access",
                "sub": context.user_id,
                "org": context.org_id,
                "roles": list(context.roles),
                "permissions": list(context.permissions),
                "ver": context.token_version,
                "iat": int(issued_at.timestamp()),
                "exp": int((issued_at + timedelta(seconds=self._access_ttl_seconds)).timestamp()),
            }
        )

    def issue_refresh_token(self) -> str:
        return f"rfr_{secrets.token_urlsafe(32)}"

    def decode_access_token(
        self,
        token: str,
        trace_id: str,
        now: datetime | None = None,
    ) -> AuthContext:
        payload = self._decode(token, now=now)
        if payload.get("typ") != "access":
            raise InvalidCredentials("Token type is not access.")
        return AuthContext(
            user_id=str(payload["sub"]),
            org_id=str(payload["org"]),
            roles=tuple(str(role) for role in _sequence(payload.get("roles"))),
            permissions=tuple(
                str(permission) for permission in _sequence(payload.get("permissions"))
            ),
            trace_id=trace_id,
            token_version=int(payload.get("ver", 1)),
        )

    def hash_refresh_token(self, token: str) -> str:
        return hmac.new(self._secret, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def refresh_expires_at(self, now: datetime | None = None) -> datetime:
        return (now or utc_now()) + timedelta(seconds=self._refresh_ttl_seconds)

    def _encode(self, payload: Mapping[str, object]) -> str:
        body = _b64_json(payload)
        signature = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64_bytes(signature)}"

    def _decode(self, token: str, now: datetime | None = None) -> Mapping[str, Any]:
        try:
            body, signature_text = token.split(".", 1)
            expected = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
            actual = _unb64_bytes(signature_text)
            if not hmac.compare_digest(actual, expected):
                raise InvalidCredentials("Token signature is invalid.")
            payload = cast(Mapping[str, Any], json.loads(_unb64_bytes(body)))
            expires_at = int(payload.get("exp", 0))
        except (ValueError, TypeError, json.JSONDecodeError):
            raise InvalidCredentials("Token is malformed.") from None
        if expires_at <= int((now or utc_now()).timestamp()):
            raise TokenExpired("Token is expired.")
        return payload


class InMemoryAuthStore:
    def __init__(self) -> None:
        self._organizations: dict[str, OrganizationRecord] = {}
        self._users_by_id: dict[str, UserRecord] = {}
        self._user_ids_by_email: dict[str, str] = {}
        self._refresh_sessions: dict[str, RefreshSessionRecord] = {}
        self._session_ids_by_refresh_hash: dict[str, str] = {}
        self._role_audit_events: list[RoleAuditEvent] = []

    def create_organization(self, name: str) -> OrganizationRecord:
        org_id = f"org_{secrets.token_hex(8)}"
        record = OrganizationRecord(org_id=org_id, name=name.strip() or "Default Organization")
        self._organizations[org_id] = record
        return record

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        org_id: str,
        roles: Sequence[str],
        permissions: Sequence[str],
    ) -> UserRecord:
        normalized_email = normalize_email(email)
        if normalized_email in self._user_ids_by_email:
            raise ValueError("email already exists")
        user_id = f"user_{secrets.token_hex(8)}"
        record = UserRecord(
            user_id=user_id,
            email=normalized_email,
            display_name=display_name.strip(),
            password_hash=password_hash,
            org_id=org_id,
            roles=tuple(dict.fromkeys(roles)),
            permissions=tuple(dict.fromkeys(permissions)),
        )
        self._users_by_id[user_id] = record
        self._user_ids_by_email[normalized_email] = user_id
        return record

    def get_user_by_email(self, email: str) -> UserRecord | None:
        user_id = self._user_ids_by_email.get(normalize_email(email))
        if user_id is None:
            return None
        return self._users_by_id.get(user_id)

    def get_user(self, user_id: str) -> UserRecord | None:
        return self._users_by_id.get(user_id)

    def update_user_roles(
        self,
        *,
        actor: AuthContext,
        target_user_id: str,
        roles: Sequence[str],
        permissions: Sequence[str],
    ) -> UserRecord:
        target = self._users_by_id.get(target_user_id)
        if target is None or target.org_id != actor.org_id:
            raise KeyError("target user was not found")
        updated = replace(
            target,
            roles=tuple(dict.fromkeys(roles)),
            permissions=tuple(dict.fromkeys(permissions)),
            token_version=target.token_version + 1,
        )
        self._users_by_id[target_user_id] = updated
        self._role_audit_events.append(
            RoleAuditEvent(
                audit_event_id=f"aud_{secrets.token_hex(8)}",
                org_id=actor.org_id,
                actor_user_id=actor.user_id,
                target_user_id=target_user_id,
                action="user.roles_updated",
                roles_before=target.roles,
                roles_after=updated.roles,
                permissions_before=target.permissions,
                permissions_after=updated.permissions,
            )
        )
        return updated

    def create_refresh_session(
        self,
        *,
        user_id: str,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> RefreshSessionRecord:
        session_id = f"sess_{secrets.token_hex(8)}"
        record = RefreshSessionRecord(
            session_id=session_id,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
        )
        self._refresh_sessions[session_id] = record
        self._session_ids_by_refresh_hash[refresh_token_hash] = session_id
        return record

    def get_refresh_session_by_token_hash(
        self,
        refresh_token_hash: str,
    ) -> RefreshSessionRecord | None:
        session_id = self._session_ids_by_refresh_hash.get(refresh_token_hash)
        if session_id is None:
            return None
        return self._refresh_sessions.get(session_id)

    def revoke_refresh_session(self, session_id: str) -> None:
        record = self._refresh_sessions.get(session_id)
        if record is None or record.revoked_at is not None:
            return
        self._refresh_sessions[session_id] = replace(record, revoked_at=utc_now())

    def list_role_audit_events(self, org_id: str) -> tuple[RoleAuditEvent, ...]:
        return tuple(event for event in self._role_audit_events if event.org_id == org_id)


class PostgresAuthStore:
    _user_columns = (
        "user_id",
        "email",
        "display_name",
        "password_hash",
        "org_id",
        "roles",
        "permissions",
        "token_version",
        "created_at",
    )
    _refresh_session_columns = (
        "session_id",
        "user_id",
        "refresh_token_hash",
        "expires_at",
        "revoked_at",
        "created_at",
    )
    _role_audit_columns = (
        "audit_event_id",
        "org_id",
        "actor_user_id",
        "target_user_id",
        "action",
        "roles_before",
        "roles_after",
        "permissions_before",
        "permissions_after",
        "occurred_at",
    )

    def __init__(self, connection: AuthConnection) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        self._connection.execute(AUTH_TABLES_SQL)
        self._connection.commit()

    def create_organization(self, name: str) -> OrganizationRecord:
        created_at = utc_now()
        record = OrganizationRecord(
            org_id=f"org_{secrets.token_hex(8)}",
            name=name.strip() or "Default Organization",
            created_at=created_at,
        )
        self._connection.execute(
            """
            INSERT INTO auth.organizations (
                org_id,
                name,
                created_at
            )
            VALUES (%s, %s, %s)
            """,
            (record.org_id, record.name, record.created_at),
        )
        self._connection.commit()
        return record

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        org_id: str,
        roles: Sequence[str],
        permissions: Sequence[str],
    ) -> UserRecord:
        normalized_email = normalize_email(email)
        if self.get_user_by_email(normalized_email) is not None:
            raise ValueError("email already exists")

        created_at = utc_now()
        record = UserRecord(
            user_id=f"user_{secrets.token_hex(8)}",
            email=normalized_email,
            display_name=display_name.strip(),
            password_hash=password_hash,
            org_id=org_id,
            roles=tuple(dict.fromkeys(roles)),
            permissions=tuple(dict.fromkeys(permissions)),
            created_at=created_at,
        )
        self._connection.execute(
            """
            INSERT INTO auth.users (
                user_id,
                email,
                display_name,
                password_hash,
                org_id,
                roles,
                permissions,
                token_version,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.user_id,
                record.email,
                record.display_name,
                record.password_hash,
                record.org_id,
                list(record.roles),
                list(record.permissions),
                record.token_version,
                record.created_at,
                record.created_at,
            ),
        )
        self._connection.commit()
        return record

    def get_user_by_email(self, email: str) -> UserRecord | None:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._user_columns)}
            FROM auth.users
            WHERE LOWER(email) = LOWER(%s)
            """,
            (normalize_email(email),),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def get_user(self, user_id: str) -> UserRecord | None:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._user_columns)}
            FROM auth.users
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def update_user_roles(
        self,
        *,
        actor: AuthContext,
        target_user_id: str,
        roles: Sequence[str],
        permissions: Sequence[str],
    ) -> UserRecord:
        target = self.get_user(target_user_id)
        if target is None or target.org_id != actor.org_id:
            raise KeyError("target user was not found")

        updated_roles = tuple(dict.fromkeys(roles))
        updated_permissions = tuple(dict.fromkeys(permissions))
        self._connection.execute(
            """
            UPDATE auth.users
            SET roles = %s,
                permissions = %s,
                token_version = token_version + 1,
                updated_at = %s
            WHERE user_id = %s
              AND org_id = %s
            """,
            (
                list(updated_roles),
                list(updated_permissions),
                utc_now(),
                target_user_id,
                actor.org_id,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO auth.role_audit_events (
                audit_event_id,
                org_id,
                actor_user_id,
                target_user_id,
                action,
                roles_before,
                roles_after,
                permissions_before,
                permissions_after,
                occurred_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"aud_{secrets.token_hex(8)}",
                actor.org_id,
                actor.user_id,
                target_user_id,
                "user.roles_updated",
                list(target.roles),
                list(updated_roles),
                list(target.permissions),
                list(updated_permissions),
                utc_now(),
            ),
        )
        self._connection.commit()
        return replace(
            target,
            roles=updated_roles,
            permissions=updated_permissions,
            token_version=target.token_version + 1,
        )

    def create_refresh_session(
        self,
        *,
        user_id: str,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> RefreshSessionRecord:
        record = RefreshSessionRecord(
            session_id=f"sess_{secrets.token_hex(8)}",
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            created_at=utc_now(),
        )
        self._connection.execute(
            """
            INSERT INTO auth.refresh_sessions (
                session_id,
                user_id,
                refresh_token_hash,
                expires_at,
                revoked_at,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                record.session_id,
                record.user_id,
                record.refresh_token_hash,
                record.expires_at,
                record.revoked_at,
                record.created_at,
            ),
        )
        self._connection.commit()
        return record

    def get_refresh_session_by_token_hash(
        self,
        refresh_token_hash: str,
    ) -> RefreshSessionRecord | None:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._refresh_session_columns)}
            FROM auth.refresh_sessions
            WHERE refresh_token_hash = %s
            """,
            (refresh_token_hash,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None
        return self._row_to_refresh_session(row)

    def revoke_refresh_session(self, session_id: str) -> None:
        self._connection.execute(
            """
            UPDATE auth.refresh_sessions
            SET revoked_at = COALESCE(revoked_at, %s)
            WHERE session_id = %s
            """,
            (utc_now(), session_id),
        )
        self._connection.commit()

    def list_role_audit_events(self, org_id: str) -> tuple[RoleAuditEvent, ...]:
        self._connection.execute(
            f"""
            SELECT {", ".join(self._role_audit_columns)}
            FROM auth.role_audit_events
            WHERE org_id = %s
            ORDER BY occurred_at ASC
            """,
            (org_id,),
        )
        return tuple(self._row_to_role_audit_event(row) for row in self._connection.fetchall())

    def _row_to_user(self, row: Sequence[object]) -> UserRecord:
        if len(row) not in {len(self._user_columns), len(self._user_columns) - 1}:
            raise ValueError("auth user row has unexpected column count.")
        token_version = 1 if len(row) == len(self._user_columns) - 1 else int(row[7])
        created_at_index = 7 if len(row) == len(self._user_columns) - 1 else 8
        return UserRecord(
            user_id=cast(str, row[0]),
            email=cast(str, row[1]),
            display_name=cast(str, row[2]),
            password_hash=cast(str, row[3]),
            org_id=cast(str, row[4]),
            roles=_tuple_from_db(row[5]),
            permissions=_tuple_from_db(row[6]),
            token_version=token_version,
            created_at=cast(datetime, row[created_at_index]),
        )

    def _row_to_refresh_session(self, row: Sequence[object]) -> RefreshSessionRecord:
        if len(row) != len(self._refresh_session_columns):
            raise ValueError("auth refresh session row has unexpected column count.")
        return RefreshSessionRecord(
            session_id=cast(str, row[0]),
            user_id=cast(str, row[1]),
            refresh_token_hash=cast(str, row[2]),
            expires_at=cast(datetime, row[3]),
            revoked_at=cast(datetime | None, row[4]),
            created_at=cast(datetime, row[5]),
        )

    def _row_to_role_audit_event(self, row: Sequence[object]) -> RoleAuditEvent:
        if len(row) != len(self._role_audit_columns):
            raise ValueError("auth role audit row has unexpected column count.")
        return RoleAuditEvent(
            audit_event_id=cast(str, row[0]),
            org_id=cast(str, row[1]),
            actor_user_id=cast(str, row[2]),
            target_user_id=cast(str, row[3]),
            action=cast(str, row[4]),
            roles_before=_tuple_from_db(row[5]),
            roles_after=_tuple_from_db(row[6]),
            permissions_before=_tuple_from_db(row[7]),
            permissions_after=_tuple_from_db(row[8]),
            occurred_at=cast(datetime, row[9]),
        )


class AuthService:
    def __init__(
        self,
        store: AuthStore | None = None,
        password_hasher: PasswordHasher | None = None,
        token_service: TokenService | None = None,
    ) -> None:
        self._store = store or InMemoryAuthStore()
        self._password_hasher = password_hasher or PasswordHasher()
        self._token_service = token_service or TokenService()

    @property
    def store(self) -> AuthStore:
        return self._store

    def sign_up(self, request: SignUpRequest) -> tuple[UserRecord, AuthTokenPair]:
        org = self._store.create_organization(request.organization_name or "Default Organization")
        user = self._store.create_user(
            email=request.email,
            password_hash=self._password_hasher.hash_password(request.password),
            display_name=request.display_name,
            org_id=org.org_id,
            roles=("business_user",),
            permissions=permissions_for_roles(("business_user",)),
        )
        return user, self._issue_pair(user)

    def sign_in(self, email: str, password: str) -> tuple[UserRecord, AuthTokenPair]:
        user = self._store.get_user_by_email(email)
        if user is None or not self._password_hasher.verify_password(
            password,
            user.password_hash,
        ):
            raise InvalidCredentials("Email or password is invalid.")
        return user, self._issue_pair(user)

    def refresh(self, refresh_token: str) -> tuple[UserRecord, AuthTokenPair]:
        token_hash = self._token_service.hash_refresh_token(refresh_token)
        session = self._store.get_refresh_session_by_token_hash(token_hash)
        if session is None or not session.active:
            raise InvalidCredentials("Refresh token is invalid.")
        user = self._store.get_user(session.user_id)
        if user is None:
            raise InvalidCredentials("Refresh token is invalid.")
        self._store.revoke_refresh_session(session.session_id)
        return user, self._issue_pair(user)

    def revoke_refresh_token(self, refresh_token: str) -> None:
        token_hash = self._token_service.hash_refresh_token(refresh_token)
        session = self._store.get_refresh_session_by_token_hash(token_hash)
        if session is not None:
            self._store.revoke_refresh_session(session.session_id)

    def authenticate_access_token(self, token: str, trace_id: str) -> AuthContext:
        context = self._token_service.decode_access_token(token, trace_id=trace_id)
        user = self._store.get_user(context.user_id)
        if (
            user is None
            or user.org_id != context.org_id
            or user.token_version != context.token_version
        ):
            raise InvalidCredentials("Access token is stale or invalid.")
        return AuthContext(
            user_id=user.user_id,
            org_id=user.org_id,
            roles=user.roles,
            permissions=user.permissions,
            trace_id=trace_id,
            token_version=user.token_version,
        )

    def update_user_roles(
        self,
        *,
        actor: AuthContext,
        target_user_id: str,
        roles: Sequence[str],
    ) -> UserRecord:
        require_permission(actor, "admin:user:write")
        return self._store.update_user_roles(
            actor=actor,
            target_user_id=target_user_id,
            roles=roles,
            permissions=permissions_for_roles(roles),
        )

    def list_role_audit_events(self, actor: AuthContext) -> tuple[RoleAuditEvent, ...]:
        require_permission(actor, "admin:audit:read")
        return self._store.list_role_audit_events(actor.org_id)

    def _issue_pair(self, user: UserRecord) -> AuthTokenPair:
        context = AuthContext(
            user_id=user.user_id,
            org_id=user.org_id,
            roles=user.roles,
            permissions=user.permissions,
            token_version=user.token_version,
        )
        refresh_token = self._token_service.issue_refresh_token()
        self._store.create_refresh_session(
            user_id=user.user_id,
            refresh_token_hash=self._token_service.hash_refresh_token(refresh_token),
            expires_at=self._token_service.refresh_expires_at(),
        )
        return AuthTokenPair(
            access_token=self._token_service.issue_access_token(context),
            refresh_token=refresh_token,
            expires_in=self._token_service.access_ttl_seconds,
        )


ROLE_PERMISSIONS: Mapping[str, tuple[str, ...]] = {
    "business_user": (
        "chat:query",
        "chat:history:read:self",
        "query:read:self",
    ),
    "analyst": (
        "chat:query",
        "chat:history:read:self",
        "query:read:self",
        "analytics:run",
        "eval:read:approved",
    ),
    "admin": (
        "chat:query",
        "chat:history:read:self",
        "query:read:self",
        "admin:trace:read",
        "admin:eval:read",
        "admin:eval:write",
        "admin:release_gate:read",
        "admin:user:write",
        "admin:audit:read",
        "documents:index",
        "analytics:run",
    ),
}


def permissions_for_roles(roles: Sequence[str]) -> tuple[str, ...]:
    permissions: list[str] = []
    for role in roles:
        permissions.extend(ROLE_PERMISSIONS.get(role, ()))
    return tuple(dict.fromkeys(permissions))


def require_permission(context: AuthContext, permission: str) -> None:
    if permission not in context.permissions:
        raise PermissionDenied(f"Missing permission: {permission}")


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized:
        raise ValueError("email must be valid")
    return normalized


def dev_test_auth_context(trace_id: str) -> AuthContext:
    return AuthContext(
        user_id="u_001",
        org_id="org_test",
        roles=("admin",),
        permissions=permissions_for_roles(("admin",)),
        trace_id=trace_id,
    )


def postgres_auth_store_from_psycopg(connection: Any) -> PostgresAuthStore:
    return PostgresAuthStore(PsycopgAuthConnection(connection))


def connect_psycopg(database_url: str) -> Any:
    psycopg = importlib.import_module("psycopg")
    return psycopg.connect(database_url)


def _tuple_from_db(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        if stripped.startswith("["):
            try:
                loaded = json.loads(stripped)
                return tuple(str(item) for item in _sequence(loaded))
            except json.JSONDecodeError:
                return (stripped,)
        return (stripped,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in cast(Sequence[object], value))
    return (str(value),)


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, list | tuple):
        return tuple(cast(Sequence[object], value))
    return ()


def _b64_json(payload: Mapping[str, object]) -> str:
    return _b64_bytes(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


def _b64_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
