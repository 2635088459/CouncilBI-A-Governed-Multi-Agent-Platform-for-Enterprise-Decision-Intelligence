"""Runtime configuration for the deployable ChatBI services.

The v2 architecture spec names these variables as deployment contracts:
``DATABASE_URL``, ``CHATBI_READONLY_DATABASE_URL``, ``REDIS_URL``, and
``VECTOR_STORE_URL``. This module turns those environment variables into one
typed object so service code does not scatter raw ``os.environ`` lookups
everywhere.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    database_url: str | None = None
    readonly_database_url: str | None = None
    redis_url: str | None = None
    vector_store_url: str | None = None
    service_name: str = "chatbi-api"

    @property
    def postgresql_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def readonly_postgresql_configured(self) -> bool:
        return bool(self.readonly_database_url)

    @property
    def redis_configured(self) -> bool:
        return bool(self.redis_url)

    @property
    def vector_store_configured(self) -> bool:
        return bool(self.vector_store_url)

    @property
    def ready_for_traffic(self) -> bool:
        """Readiness starts with the database because chat answers are stateful."""

        return self.postgresql_configured

    def dependency_status(self) -> dict[str, dict[str, bool]]:
        return {
            "postgresql": {"configured": self.postgresql_configured},
            "business_postgresql_readonly": {
                "configured": self.readonly_postgresql_configured,
            },
            "redis": {"configured": self.redis_configured},
            "vector_store": {"configured": self.vector_store_configured},
        }


def load_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    runtime_env = env or os.environ
    return RuntimeConfig(
        database_url=_non_empty(runtime_env.get("DATABASE_URL")),
        readonly_database_url=_non_empty(runtime_env.get("CHATBI_READONLY_DATABASE_URL")),
        redis_url=_non_empty(runtime_env.get("REDIS_URL")),
        vector_store_url=_non_empty(runtime_env.get("VECTOR_STORE_URL")),
    )


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class DatabaseReadinessCursor(Protocol):
    def fetchone(self) -> Sequence[object] | None:
        ...


class DatabaseReadinessConnection(Protocol):
    def execute(self, sql: str) -> DatabaseReadinessCursor:
        ...

    def close(self) -> None:
        ...


class DatabaseReadinessChecker:
    """Optional live database ping for readiness probes."""

    def __init__(self, connect: Callable[[str], DatabaseReadinessConnection]) -> None:
        self._connect = connect

    def is_ready(self, database_url: str | None) -> bool:
        if database_url is None:
            return False
        try:
            connection = self._connect(database_url)
            cursor = connection.execute("SELECT 1")
            row = cursor.fetchone()
            connection.close()
        except Exception:
            return False
        return row == (1,) or row == [1]


class RedisReadinessClient(Protocol):
    def ping(self) -> bool:
        ...

    def close(self) -> None:
        ...


class RedisTcpPingClient:
    """Tiny stdlib Redis PING client for container readiness probes."""

    def __init__(self, redis_url: str, timeout_seconds: float = 1.0) -> None:
        parsed = urlparse(redis_url)
        host = parsed.hostname
        if host is None:
            raise ValueError("redis_url must include a host")
        self._socket = socket.create_connection(
            (host, parsed.port or 6379),
            timeout=timeout_seconds,
        )

    def ping(self) -> bool:
        self._socket.sendall(b"*1\r\n$4\r\nPING\r\n")
        return self._socket.recv(16).startswith(b"+PONG")

    def close(self) -> None:
        self._socket.close()


class RedisReadinessChecker:
    """Optional live Redis PING for readiness probes."""

    def __init__(self, connect: Callable[[str], RedisReadinessClient]) -> None:
        self._connect = connect

    def is_ready(self, redis_url: str | None) -> bool:
        if redis_url is None:
            return False
        try:
            client = self._connect(redis_url)
            ready = client.ping()
            client.close()
        except Exception:
            return False
        return ready
