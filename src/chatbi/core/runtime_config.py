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
    llm_provider: str = "mock"
    llm_model: str = "mock-chatbi-small"
    llm_timeout_ms: int = 1000
    llm_max_retries: int = 1
    llm_backoff_ms: int = 25
    llm_api_key_configured: bool = False
    embedding_provider: str = "mock"
    embedding_model: str = "mock-local-embedding"
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
    def llm_provider_configured(self) -> bool:
        if self.llm_provider == "mock":
            return True
        return self.llm_api_key_configured

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
            "llm_provider": {
                "configured": self.llm_provider_configured,
                "mock": self.llm_provider == "mock",
            },
            "embedding_provider": {
                "configured": self.embedding_provider == "mock",
                "mock": self.embedding_provider == "mock",
            },
        }


def load_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    runtime_env = env or os.environ
    llm_provider = _non_empty(runtime_env.get("CHATBI_LLM_PROVIDER")) or "mock"
    return RuntimeConfig(
        database_url=_non_empty(runtime_env.get("DATABASE_URL")),
        readonly_database_url=_non_empty(runtime_env.get("CHATBI_READONLY_DATABASE_URL")),
        redis_url=_non_empty(runtime_env.get("REDIS_URL")),
        vector_store_url=_non_empty(runtime_env.get("VECTOR_STORE_URL")),
        llm_provider=llm_provider,
        llm_model=_llm_model_from_env(runtime_env, llm_provider),
        llm_timeout_ms=_positive_int(runtime_env.get("CHATBI_LLM_TIMEOUT_MS"), 1000),
        llm_max_retries=_non_negative_int(runtime_env.get("CHATBI_LLM_MAX_RETRIES"), 1),
        llm_backoff_ms=_non_negative_int(runtime_env.get("CHATBI_LLM_BACKOFF_MS"), 25),
        llm_api_key_configured=_non_empty(runtime_env.get("OPENAI_API_KEY")) is not None,
        embedding_provider=_non_empty(runtime_env.get("CHATBI_EMBEDDING_PROVIDER")) or "mock",
        embedding_model=_non_empty(runtime_env.get("CHATBI_EMBEDDING_MODEL"))
        or "mock-local-embedding",
    )


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _llm_model_from_env(runtime_env: Mapping[str, str], llm_provider: str) -> str:
    configured_model = _non_empty(runtime_env.get("CHATBI_LLM_MODEL")) or _non_empty(
        runtime_env.get("OPENAI_MODEL")
    )
    if configured_model is not None:
        return configured_model
    if llm_provider.strip().lower() == "openai":
        return "gpt-4o-mini"
    return "mock-chatbi-small"


def _positive_int(value: str | None, default: int) -> int:
    parsed = _int_or_default(value, default)
    return parsed if parsed > 0 else default


def _non_negative_int(value: str | None, default: int) -> int:
    parsed = _int_or_default(value, default)
    return parsed if parsed >= 0 else default


def _int_or_default(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


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
