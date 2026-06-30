"""Runtime probe for least-privilege business database credentials."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Protocol


READONLY_WRITE_PROBE_SQL = "CREATE TABLE guardrail_probe(id int)"


class ReadOnlyProbeStatus(StrEnum):
    BLOCKED = "blocked"
    WRITE_ALLOWED = "write_allowed"
    PROBE_FAILED = "probe_failed"


@dataclass(frozen=True, slots=True)
class ReadOnlyProbeResult:
    status: ReadOnlyProbeStatus
    probe_sql: str = READONLY_WRITE_PROBE_SQL
    message: str | None = None

    @property
    def passed(self) -> bool:
        return self.status is ReadOnlyProbeStatus.BLOCKED


class ReadOnlyProbeConnection(Protocol):
    def execute(self, sql: str) -> object:
        ...

    def rollback(self) -> None:
        ...

    def close(self) -> None:
        ...


class ReadOnlyDatabaseProbeRunner(Protocol):
    def check(self, database_url: str | None) -> ReadOnlyProbeResult:
        ...


class ReadOnlyDatabaseProbe:
    """Verify that the runtime business database connection cannot write."""

    def __init__(
        self,
        connect: Callable[[str], ReadOnlyProbeConnection],
        probe_sql: str = READONLY_WRITE_PROBE_SQL,
    ) -> None:
        self._connect = connect
        self._probe_sql = probe_sql

    def check(self, database_url: str | None) -> ReadOnlyProbeResult:
        if database_url is None or not database_url.strip():
            return ReadOnlyProbeResult(
                status=ReadOnlyProbeStatus.PROBE_FAILED,
                probe_sql=self._probe_sql,
                message="Read-only database URL is not configured.",
            )

        try:
            connection = self._connect(database_url)
        except Exception:
            return ReadOnlyProbeResult(
                status=ReadOnlyProbeStatus.PROBE_FAILED,
                probe_sql=self._probe_sql,
                message="Read-only database connection failed.",
            )

        try:
            connection.execute(self._probe_sql)
        except Exception as exc:
            self._rollback_quietly(connection)
            self._close_quietly(connection)
            if not self._is_readonly_or_permission_error(exc):
                return ReadOnlyProbeResult(
                    status=ReadOnlyProbeStatus.PROBE_FAILED,
                    probe_sql=self._probe_sql,
                    message="Read-only write probe execution failed.",
                )
            return ReadOnlyProbeResult(
                status=ReadOnlyProbeStatus.BLOCKED,
                probe_sql=self._probe_sql,
                message="Write probe was blocked by database permissions.",
            )

        self._rollback_quietly(connection)
        self._close_quietly(connection)
        return ReadOnlyProbeResult(
            status=ReadOnlyProbeStatus.WRITE_ALLOWED,
            probe_sql=self._probe_sql,
            message="Write probe unexpectedly succeeded.",
        )

    def _rollback_quietly(self, connection: ReadOnlyProbeConnection | None) -> None:
        if connection is None:
            return
        try:
            connection.rollback()
        except Exception:
            return

    def _close_quietly(self, connection: ReadOnlyProbeConnection | None) -> None:
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            return

    def _is_readonly_or_permission_error(self, exc: Exception) -> bool:
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate in {"25006", "42501"}:
            return True

        message = str(exc).lower()
        return any(
            phrase in message
            for phrase in (
                "permission denied",
                "insufficient privilege",
                "read-only transaction",
                "read only transaction",
                "readonly transaction",
            )
        )
