from collections.abc import Sequence
from typing import Any

from chatbi.migrate import main


class FakeMigrationCliConnection:
    def __init__(self, *, fail_on_sql: str | None = None) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.closed = False
        self.fail_on_sql = fail_on_sql

    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        self.commands.append((sql, tuple(params)))
        if self.fail_on_sql is not None and self.fail_on_sql in sql:
            raise RuntimeError("migration statement failed")
        return object()

    def fetchone(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def test_migrate_cli_requires_database_url(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "DATABASE_URL is required" in captured.err


def test_migrate_cli_applies_base_migration_from_environment(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    connection = FakeMigrationCliConnection()
    seen_urls: list[str] = []

    def connect(database_url: str) -> FakeMigrationCliConnection:
        seen_urls.append(database_url)
        return connection

    monkeypatch.setenv("DATABASE_URL", "postgresql://chatbi:secret@localhost:5432/chatbi")

    exit_code = main([], connect=connect)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert seen_urls == ["postgresql://chatbi:secret@localhost:5432/chatbi"]
    assert "Migration 001_base_runtime_foundation succeeded." in captured.out
    assert "secret" not in captured.out
    assert connection.closed is True
    assert connection.commits == 1


def test_migrate_cli_uses_explicit_database_url_over_environment(
    monkeypatch: Any,
) -> None:
    connection = FakeMigrationCliConnection()
    seen_urls: list[str] = []

    def connect(database_url: str) -> FakeMigrationCliConnection:
        seen_urls.append(database_url)
        return connection

    monkeypatch.setenv("DATABASE_URL", "postgresql://chatbi:env_secret@localhost:5432/chatbi")

    exit_code = main(
        ["--database-url", "postgresql://chatbi:arg_secret@localhost:5432/chatbi"],
        connect=connect,
    )

    assert exit_code == 0
    assert seen_urls == ["postgresql://chatbi:arg_secret@localhost:5432/chatbi"]


def test_migrate_cli_returns_failure_when_migration_fails(capsys: Any) -> None:
    connection = FakeMigrationCliConnection(fail_on_sql="runtime.messages")

    exit_code = main(
        ["--database-url", "postgresql://chatbi:super_secret@localhost:5432/chatbi"],
        connect=lambda database_url: connection,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Migration 001_base_runtime_foundation failed" in captured.err
    assert "super_secret" not in captured.err
    assert connection.closed is True
