from datetime import datetime, timezone
from typing import Sequence

from chatbi.governance import (
    GuardrailAuditConnectionV2,
    GuardrailAuditRecordV2,
    GuardrailDecisionStatus,
    GuardrailRuleCode,
    PostgresGuardrailAuditLogV2,
    PsycopgGuardrailAuditConnectionV2,
    QUERY_AUDIT_EVENTS_TABLE,
    QUERY_AUDIT_EVENTS_TABLE_SQL,
    RuleHit,
    SQL_RULE_HITS_TABLE,
    SQL_RULE_HITS_TABLE_SQL,
    postgres_guardrail_audit_log_v2_from_psycopg,
)


class FakeGuardrailAuditConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.next_row: Sequence[object] | None = None
        self.next_rows: list[Sequence[object] | None] = []

    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        self.commands.append((sql, tuple(params)))
        return object()

    def fetchone(self) -> Sequence[object] | None:
        if self.next_rows:
            return self.next_rows.pop(0)
        return self.next_row

    def commit(self) -> None:
        self.commits += 1


class FakePsycopgCursor:
    def __init__(self, row: Sequence[object] | None = None) -> None:
        self._row = row

    def fetchone(self) -> Sequence[object] | None:
        return self._row


class FakePsycopgConnection:
    def __init__(self, row: Sequence[object] | None = None) -> None:
        self.row = row
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, sql: str, params: Sequence[object] = ()) -> FakePsycopgCursor:
        self.commands.append((sql, tuple(params)))
        return FakePsycopgCursor(self.row)

    def commit(self) -> None:
        self.commits += 1


def make_audit_record() -> GuardrailAuditRecordV2:
    return GuardrailAuditRecordV2(
        audit_event_id="aud_12345678",
        trace_id="tr_12345678",
        user_id="u_001",
        role="analyst",
        sql_hash="abc123",
        decision=GuardrailDecisionStatus.DENY,
        rule_hits=(
            RuleHit(
                rule_code=GuardrailRuleCode.WRITE_OPERATION,
                message="Write operation is blocked.",
            ),
        ),
        latency_ms=12,
        org_id="org_001",
        occurred_at=datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc),
    )


def test_postgres_guardrail_audit_store_schema_matches_v2_tables() -> None:
    connection = FakeGuardrailAuditConnection()
    store = PostgresGuardrailAuditLogV2(connection)

    store.initialize_schema()

    assert QUERY_AUDIT_EVENTS_TABLE == "query_audit_events"
    assert SQL_RULE_HITS_TABLE == "sql_rule_hits"
    assert QUERY_AUDIT_EVENTS_TABLE_SQL in connection.commands[0][0]
    assert SQL_RULE_HITS_TABLE_SQL in connection.commands[1][0]
    assert connection.commits == 1


def test_postgres_guardrail_audit_store_saves_event_and_rule_hits() -> None:
    connection: GuardrailAuditConnectionV2 = FakeGuardrailAuditConnection()
    store = PostgresGuardrailAuditLogV2(connection)
    record = make_audit_record()

    store.save_v2(record)

    fake_connection = connection
    assert isinstance(fake_connection, FakeGuardrailAuditConnection)
    audit_sql, audit_params = fake_connection.commands[0]
    rule_sql, rule_params = fake_connection.commands[1]
    assert "INSERT INTO query_audit_events" in audit_sql
    assert "ON CONFLICT (audit_event_id) DO UPDATE" in audit_sql
    assert audit_params == (
        "aud_12345678",
        "org_001",
        "tr_12345678",
        "u_001",
        "analyst",
        "abc123",
        "deny",
        12,
        datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc),
    )
    assert "INSERT INTO sql_rule_hits" in rule_sql
    assert rule_params[1:] == (
        "aud_12345678",
        "tr_12345678",
        "WRITE_OPERATION",
        None,
        "Write operation is blocked.",
        datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc),
    )
    assert fake_connection.commits == 1


def test_postgres_guardrail_audit_store_loads_latest_event_by_trace_id() -> None:
    occurred_at = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    connection = FakeGuardrailAuditConnection()
    connection.next_rows = [
        (
            "aud_12345678",
            "tr_12345678",
            "u_001",
            "analyst",
            "abc123",
            "allow",
            7,
            occurred_at,
        ),
        (
            "ROW_LIMIT_REWRITE",
            "A row limit was added to the SQL.",
            None,
        ),
        None,
    ]
    store = PostgresGuardrailAuditLogV2(connection)

    record = store.get_v2("tr_12345678")

    assert record is not None
    assert record.audit_event_id == "aud_12345678"
    assert record.trace_id == "tr_12345678"
    assert record.user_id == "u_001"
    assert record.role == "analyst"
    assert record.sql_hash == "abc123"
    assert record.decision is GuardrailDecisionStatus.ALLOW
    assert record.latency_ms == 7
    assert record.org_id == "org_legacy"
    assert len(record.rule_hits) == 1
    assert record.rule_hits[0].rule_code is GuardrailRuleCode.ROW_LIMIT_REWRITE
    assert record.rule_hits[0].message == "A row limit was added to the SQL."
    assert connection.commands[0][1] == ("tr_12345678",)
    assert connection.commands[1][1] == ("aud_12345678",)


def test_postgres_guardrail_audit_store_loads_tenant_scope_from_new_rows() -> None:
    occurred_at = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    connection = FakeGuardrailAuditConnection()
    connection.next_rows = [
        (
            "aud_12345678",
            "org_001",
            "tr_12345678",
            "u_001",
            "analyst",
            "abc123",
            "allow",
            7,
            occurred_at,
        ),
        None,
    ]
    store = PostgresGuardrailAuditLogV2(connection)

    record = store.get_v2("tr_12345678")

    assert record is not None
    assert record.org_id == "org_001"
    assert record.trace_id == "tr_12345678"


def test_psycopg_guardrail_audit_connection_adapts_cursor_fetchone() -> None:
    raw_connection = FakePsycopgConnection(row=("aud_12345678",))
    connection = PsycopgGuardrailAuditConnectionV2(raw_connection)

    connection.execute("SELECT audit_event_id FROM query_audit_events WHERE trace_id = %s", ("tr_1",))
    row = connection.fetchone()
    connection.commit()

    assert row == ("aud_12345678",)
    assert raw_connection.commands == [
        (
            "SELECT audit_event_id FROM query_audit_events WHERE trace_id = %s",
            ("tr_1",),
        )
    ]
    assert raw_connection.commits == 1


def test_postgres_guardrail_audit_factory_wraps_psycopg_connection() -> None:
    raw_connection = FakePsycopgConnection()

    store = postgres_guardrail_audit_log_v2_from_psycopg(raw_connection)
    store.initialize_schema()

    assert raw_connection.commands[0][0] == QUERY_AUDIT_EVENTS_TABLE_SQL
    assert raw_connection.commands[1][0] == SQL_RULE_HITS_TABLE_SQL
    assert raw_connection.commits == 1


def test_guardrail_audit_schema_initialization_is_backward_compatible_with_old_local_volumes() -> None:
    normalized_sql = " ".join(QUERY_AUDIT_EVENTS_TABLE_SQL.split())

    assert "ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_legacy'" in normalized_sql
    assert "idx_query_audit_events_org_trace_id" in normalized_sql
