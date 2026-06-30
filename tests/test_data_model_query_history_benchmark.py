import os
import time
from typing import Any

import pytest

from chatbi.history.request_metadata import connect_psycopg
from chatbi.migrations import MigrationRunner


BENCHMARK_SESSION_ID = "sess_benchmark_history_lookup"
BENCHMARK_TRACE_PREFIX = "trc_benchmark_history_lookup_"
BENCHMARK_MESSAGE_PREFIX = "msg_benchmark_history_lookup_"
BENCHMARK_ROW_COUNT = 10_000
BENCHMARK_LIMIT = 50
MAX_LOOKUP_SECONDS = 0.25


def test_query_history_session_lookup_live_postgres_handles_10000_rows() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None or not database_url.strip():
        pytest.skip("DATABASE_URL is required for live query-history benchmark.")

    connection: Any = connect_psycopg(database_url)
    try:
        MigrationRunner(connection).apply_base_migration()
        _seed_query_history_benchmark_rows(connection)

        explain_text = _query_history_explain(connection)
        started_at = time.perf_counter()
        rows = _query_recent_history_rows(connection)
        elapsed_seconds = time.perf_counter() - started_at

        assert len(rows) == BENCHMARK_LIMIT
        assert rows[0][0] == f"{BENCHMARK_TRACE_PREFIX}{BENCHMARK_ROW_COUNT}"
        assert "idx_runtime_query_history_session_created_at" in explain_text or (
            elapsed_seconds <= MAX_LOOKUP_SECONDS
        ), explain_text
    finally:
        _close_quietly(connection)


def _seed_query_history_benchmark_rows(connection: Any) -> None:
    connection.execute(
        """
        INSERT INTO runtime.sessions (
            session_id,
            tenant_id,
            user_id,
            title,
            created_at,
            updated_at
        )
        VALUES (
            %s,
            'tenant_demo',
            'user_benchmark',
            'Benchmark query history lookup',
            '2026-06-25T00:00:00Z',
            '2026-06-25T00:00:00Z'
        )
        ON CONFLICT (session_id) DO NOTHING
        """,
        (BENCHMARK_SESSION_ID,),
    )
    connection.execute(
        """
        INSERT INTO runtime.messages (
            message_id,
            session_id,
            trace_id,
            role,
            content,
            created_at
        )
        SELECT
            %s || series_id::text,
            %s,
            %s || series_id::text,
            'user',
            'Benchmark question ' || series_id::text,
            '2026-06-25T00:00:00Z'::timestamptz + (series_id || ' seconds')::interval
        FROM generate_series(1, %s) AS series_id
        ON CONFLICT (message_id) DO NOTHING
        """,
        (
            BENCHMARK_MESSAGE_PREFIX,
            BENCHMARK_SESSION_ID,
            BENCHMARK_TRACE_PREFIX,
            BENCHMARK_ROW_COUNT,
        ),
    )
    connection.execute(
        """
        INSERT INTO runtime.query_history (
            trace_id,
            session_id,
            message_id,
            status,
            question,
            sql_text,
            final_answer,
            created_at
        )
        SELECT
            %s || series_id::text,
            %s,
            %s || series_id::text,
            'succeeded',
            'Benchmark question ' || series_id::text,
            'SELECT ' || series_id::text,
            'Benchmark answer ' || series_id::text,
            '2026-06-25T00:00:00Z'::timestamptz + (series_id || ' seconds')::interval
        FROM generate_series(1, %s) AS series_id
        ON CONFLICT (trace_id) DO NOTHING
        """,
        (
            BENCHMARK_TRACE_PREFIX,
            BENCHMARK_SESSION_ID,
            BENCHMARK_MESSAGE_PREFIX,
            BENCHMARK_ROW_COUNT,
        ),
    )
    connection.execute("ANALYZE runtime.query_history")
    connection.commit()


def _query_history_explain(connection: Any) -> str:
    cursor = connection.execute(
        """
        EXPLAIN
        SELECT trace_id, created_at
        FROM runtime.query_history
        WHERE session_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (BENCHMARK_SESSION_ID, BENCHMARK_LIMIT),
    )
    return "\n".join(str(row[0]) for row in cursor.fetchall())


def _query_recent_history_rows(connection: Any) -> list[tuple[Any, ...]]:
    cursor = connection.execute(
        """
        SELECT trace_id, created_at
        FROM runtime.query_history
        WHERE session_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (BENCHMARK_SESSION_ID, BENCHMARK_LIMIT),
    )
    return list(cursor.fetchall())


def _close_quietly(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if not callable(close):
        return
    close()
