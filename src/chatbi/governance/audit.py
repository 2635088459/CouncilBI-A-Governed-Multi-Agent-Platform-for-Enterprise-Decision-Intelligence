"""In-memory audit log for guardrail decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Sequence, cast
from uuid import uuid4

from chatbi.core.contracts import ErrorCode, GuardrailDecision, UserRole, utc_now
from chatbi.governance.contracts import GuardrailDecisionStatus, GuardrailRuleCode, RuleHit


QUERY_AUDIT_EVENTS_TABLE = "query_audit_events"
SQL_RULE_HITS_TABLE = "sql_rule_hits"

QUERY_AUDIT_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS query_audit_events (
    audit_event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    sql_hash TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny')),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_query_audit_events_trace_id
    ON query_audit_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_query_audit_events_sql_hash
    ON query_audit_events(sql_hash);
CREATE INDEX IF NOT EXISTS idx_query_audit_events_decision
    ON query_audit_events(decision);
"""

SQL_RULE_HITS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sql_rule_hits (
    rule_hit_id TEXT PRIMARY KEY,
    audit_event_id TEXT NOT NULL REFERENCES query_audit_events(audit_event_id),
    trace_id TEXT NOT NULL,
    rule_code TEXT NOT NULL,
    object_name TEXT,
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sql_rule_hits_audit_event_id
    ON sql_rule_hits(audit_event_id);
CREATE INDEX IF NOT EXISTS idx_sql_rule_hits_trace_id
    ON sql_rule_hits(trace_id);
CREATE INDEX IF NOT EXISTS idx_sql_rule_hits_rule_code
    ON sql_rule_hits(rule_code);
"""


def new_audit_event_id() -> str:
    return f"aud_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class GuardrailAuditRecord:
    trace_id: str
    user_id: str
    role: UserRole
    original_sql: str
    decision: GuardrailDecision
    audit_event_id: str = field(default_factory=new_audit_event_id)
    occurred_at: datetime = field(default_factory=utc_now)
    safe_sql: str | None = None
    error_code: ErrorCode | None = None
    message: str | None = None


class GuardrailAuditLog(Protocol):
    def save(self, record: GuardrailAuditRecord) -> None:
        """Save one guardrail decision for audit and replay."""
        ...

    def get(self, trace_id: str) -> GuardrailAuditRecord | None:
        """Replay the latest guardrail decision by trace id."""
        ...


class InMemoryGuardrailAuditLog:
    """Small audit store used by tests and the local demo runtime."""

    def __init__(self) -> None:
        self._records: list[GuardrailAuditRecord] = []

    def save(self, record: GuardrailAuditRecord) -> None:
        self._records.append(record)

    def get(self, trace_id: str) -> GuardrailAuditRecord | None:
        for record in reversed(self._records):
            if record.trace_id == trace_id:
                return record
        return None

    def list_by_trace_id(self, trace_id: str) -> tuple[GuardrailAuditRecord, ...]:
        return tuple(record for record in self._records if record.trace_id == trace_id)

    def list_all(self) -> tuple[GuardrailAuditRecord, ...]:
        return tuple(self._records)


@dataclass(frozen=True, slots=True)
class GuardrailAuditRecordV2:
    trace_id: str
    user_id: str
    role: str
    sql_hash: str
    decision: GuardrailDecisionStatus
    rule_hits: tuple[RuleHit, ...]
    latency_ms: int
    audit_event_id: str = field(default_factory=new_audit_event_id)
    occurred_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.trace_id.strip():
            raise ValueError("trace_id is required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if not self.role.strip():
            raise ValueError("role is required")
        if not self.sql_hash.strip():
            raise ValueError("sql_hash is required")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be greater than or equal to 0")


class GuardrailAuditLogV2(Protocol):
    def save_v2(self, record: GuardrailAuditRecordV2) -> None:
        """Save one v2 guardrail decision for audit and replay."""
        ...

    def get_v2(self, trace_id: str) -> GuardrailAuditRecordV2 | None:
        """Replay the latest v2 guardrail decision by trace id."""
        ...


class GuardrailAuditConnectionV2(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        ...

    def fetchone(self) -> Sequence[object] | None:
        ...

    def commit(self) -> None:
        ...


class PsycopgGuardrailAuditConnectionV2:
    """Adapt a psycopg-style connection to GuardrailAuditConnectionV2."""

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

    def commit(self) -> None:
        self._connection.commit()


class InMemoryGuardrailAuditLogV2:
    """Small v2 audit store used by tests and local development."""

    def __init__(self) -> None:
        self._records: list[GuardrailAuditRecordV2] = []

    def save_v2(self, record: GuardrailAuditRecordV2) -> None:
        self._records.append(record)

    def get_v2(self, trace_id: str) -> GuardrailAuditRecordV2 | None:
        for record in reversed(self._records):
            if record.trace_id == trace_id:
                return record
        return None

    def list_by_trace_id_v2(self, trace_id: str) -> tuple[GuardrailAuditRecordV2, ...]:
        return tuple(record for record in self._records if record.trace_id == trace_id)

    def list_all_v2(self) -> tuple[GuardrailAuditRecordV2, ...]:
        return tuple(self._records)


class PostgresGuardrailAuditLogV2:
    """PostgreSQL-backed audit log for v2 guardrail decisions."""

    def __init__(self, connection: GuardrailAuditConnectionV2) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        self._connection.execute(QUERY_AUDIT_EVENTS_TABLE_SQL)
        self._connection.execute(SQL_RULE_HITS_TABLE_SQL)
        self._connection.commit()

    def save_v2(self, record: GuardrailAuditRecordV2) -> None:
        self._connection.execute(
            """
            INSERT INTO query_audit_events (
                audit_event_id,
                trace_id,
                user_id,
                role,
                sql_hash,
                decision,
                latency_ms,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (audit_event_id) DO UPDATE SET
                trace_id = EXCLUDED.trace_id,
                user_id = EXCLUDED.user_id,
                role = EXCLUDED.role,
                sql_hash = EXCLUDED.sql_hash,
                decision = EXCLUDED.decision,
                latency_ms = EXCLUDED.latency_ms,
                created_at = EXCLUDED.created_at
            """,
            (
                record.audit_event_id,
                record.trace_id,
                record.user_id,
                record.role,
                record.sql_hash,
                record.decision.value,
                record.latency_ms,
                record.occurred_at,
            ),
        )
        for rule_hit in record.rule_hits:
            self._connection.execute(
                """
                INSERT INTO sql_rule_hits (
                    rule_hit_id,
                    audit_event_id,
                    trace_id,
                    rule_code,
                    object_name,
                    message,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"rule_{uuid4().hex}",
                    record.audit_event_id,
                    record.trace_id,
                    rule_hit.rule_code.value,
                    rule_hit.object_name,
                    rule_hit.message,
                    record.occurred_at,
                ),
            )
        self._connection.commit()

    def get_v2(self, trace_id: str) -> GuardrailAuditRecordV2 | None:
        self._connection.execute(
            """
            SELECT
                audit_event_id,
                trace_id,
                user_id,
                role,
                sql_hash,
                decision,
                latency_ms,
                created_at
            FROM query_audit_events
            WHERE trace_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (trace_id,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None

        audit_event_id = cast(str, row[0])
        return GuardrailAuditRecordV2(
            audit_event_id=cast(str, row[0]),
            trace_id=cast(str, row[1]),
            user_id=cast(str, row[2]),
            role=cast(str, row[3]),
            sql_hash=cast(str, row[4]),
            decision=GuardrailDecisionStatus(cast(str, row[5])),
            latency_ms=cast(int, row[6]),
            occurred_at=cast(datetime, row[7]),
            rule_hits=self._rule_hits_for_audit_event(audit_event_id),
        )

    def _rule_hits_for_audit_event(self, audit_event_id: str) -> tuple[RuleHit, ...]:
        self._connection.execute(
            """
            SELECT
                rule_code,
                message,
                object_name
            FROM sql_rule_hits
            WHERE audit_event_id = %s
            ORDER BY created_at ASC
            """,
            (audit_event_id,),
        )

        rule_hits: list[RuleHit] = []
        while True:
            row = self._connection.fetchone()
            if row is None:
                break
            rule_hits.append(
                RuleHit(
                    rule_code=GuardrailRuleCode(cast(str, row[0])),
                    message=cast(str, row[1]),
                    object_name=cast(str | None, row[2]),
                )
            )
        return tuple(rule_hits)


def postgres_guardrail_audit_log_v2_from_psycopg(
    connection: Any,
) -> PostgresGuardrailAuditLogV2:
    """Build the PostgreSQL v2 guardrail audit log from a psycopg-style connection."""

    return PostgresGuardrailAuditLogV2(PsycopgGuardrailAuditConnectionV2(connection))
