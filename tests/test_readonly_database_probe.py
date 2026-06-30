from chatbi.governance.readonly_probe import (
    READONLY_WRITE_PROBE_SQL,
    ReadOnlyDatabaseProbe,
    ReadOnlyProbeStatus,
)


class FakeReadOnlyProbeConnection:
    def __init__(self, *, write_blocked: bool, execution_error: Exception | None = None) -> None:
        self.write_blocked = write_blocked
        self.execution_error = execution_error
        self.executed_sql: list[str] = []
        self.rolled_back = False
        self.closed = False

    def execute(self, sql: str) -> object:
        self.executed_sql.append(sql)
        if self.execution_error is not None:
            raise self.execution_error
        if self.write_blocked:
            raise RuntimeError("permission denied for schema public")
        return object()

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_readonly_database_probe_passes_when_create_table_is_blocked() -> None:
    connection = FakeReadOnlyProbeConnection(write_blocked=True)
    probe = ReadOnlyDatabaseProbe(lambda database_url: connection)

    result = probe.check("postgresql://chatbi_readonly:test@db:5432/chatbi")

    assert result.status is ReadOnlyProbeStatus.BLOCKED
    assert result.passed is True
    assert result.probe_sql == READONLY_WRITE_PROBE_SQL
    assert connection.executed_sql == [READONLY_WRITE_PROBE_SQL]
    assert connection.rolled_back is True
    assert connection.closed is True


def test_readonly_database_probe_fails_when_create_table_succeeds() -> None:
    connection = FakeReadOnlyProbeConnection(write_blocked=False)
    probe = ReadOnlyDatabaseProbe(lambda database_url: connection)

    result = probe.check("postgresql://chatbi_writer:test@db:5432/chatbi")

    assert result.status is ReadOnlyProbeStatus.WRITE_ALLOWED
    assert result.passed is False
    assert result.message == "Write probe unexpectedly succeeded."
    assert connection.rolled_back is True
    assert connection.closed is True


def test_readonly_database_probe_fails_when_url_is_missing() -> None:
    probe = ReadOnlyDatabaseProbe(
        lambda database_url: FakeReadOnlyProbeConnection(write_blocked=True)
    )

    result = probe.check(None)

    assert result.status is ReadOnlyProbeStatus.PROBE_FAILED
    assert result.passed is False
    assert result.message == "Read-only database URL is not configured."


def test_readonly_database_probe_fails_when_connection_cannot_open() -> None:
    def connect(database_url: str) -> FakeReadOnlyProbeConnection:
        raise RuntimeError("database unavailable")

    probe = ReadOnlyDatabaseProbe(connect)

    result = probe.check("postgresql://chatbi_readonly:test@db:5432/chatbi")

    assert result.status is ReadOnlyProbeStatus.PROBE_FAILED
    assert result.passed is False
    assert result.message == "Read-only database connection failed."


def test_readonly_database_probe_does_not_treat_unknown_execution_error_as_pass() -> None:
    connection = FakeReadOnlyProbeConnection(
        write_blocked=False,
        execution_error=RuntimeError("connection lost during execute"),
    )
    probe = ReadOnlyDatabaseProbe(lambda database_url: connection)

    result = probe.check("postgresql://chatbi_readonly:test@db:5432/chatbi")

    assert result.status is ReadOnlyProbeStatus.PROBE_FAILED
    assert result.passed is False
    assert result.message == "Read-only write probe execution failed."
    assert connection.rolled_back is True
    assert connection.closed is True


def test_readonly_database_probe_result_does_not_echo_plaintext_credentials() -> None:
    secret_url = "postgresql://chatbi_readonly:super_secret@db:5432/chatbi"
    probe = ReadOnlyDatabaseProbe(
        lambda database_url: FakeReadOnlyProbeConnection(write_blocked=True)
    )

    result = probe.check(secret_url)

    assert "super_secret" not in repr(result)
    assert secret_url not in repr(result)
