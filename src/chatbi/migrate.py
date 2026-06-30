"""Command-line entry point for applying ChatBI database migrations."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Callable, Sequence

from chatbi.history.request_metadata import connect_psycopg
from chatbi.migrations import MigrationRunner, MigrationStatus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m chatbi.migrate",
        description="Apply the ChatBI base PostgreSQL migration.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection URL. Defaults to DATABASE_URL.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    connect: Callable[[str], Any] = connect_psycopg,
) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if database_url is None or not database_url.strip():
        print("DATABASE_URL is required to apply migrations.", file=sys.stderr)
        return 2

    connection: Any | None = None
    try:
        raw_connection = connect(database_url)
        connection = raw_connection
        result = MigrationRunner(raw_connection).apply_base_migration()
    except Exception as exc:
        print(f"Migration failed before completion: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    finally:
        _close_quietly(connection)

    if result.status is MigrationStatus.SUCCEEDED:
        print(f"Migration {result.version} succeeded.")
        return 0

    print(f"Migration {result.version} failed: {result.error}", file=sys.stderr)
    return 1


def _close_quietly(connection: Any | None) -> None:
    if connection is None:
        return
    close = getattr(connection, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        return


if __name__ == "__main__":
    raise SystemExit(main())
