import os
from typing import Any

import pytest

from chatbi.history.query_history import (
    PostgresRuntimeQueryHistoryStore,
    PsycopgRuntimeQueryHistoryConnection,
)
from chatbi.history.request_metadata import connect_psycopg
from chatbi.history.trace_links import (
    PostgresTraceLinkedRecordStore,
    PsycopgTraceLinkedRecordConnection,
)
from chatbi.migrations import (
    BASE_MIGRATION_VERSION,
    DEMO_COMPLETED_QUERY_TRACE_ID,
    MigrationRunner,
    MigrationStatus,
)


def test_v2_data_model_live_postgres_migration_seed_join_and_constraints() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None or not database_url.strip():
        pytest.skip("DATABASE_URL is required for live data-model PostgreSQL integration.")

    connection: Any = connect_psycopg(database_url)
    try:
        result = MigrationRunner(connection).apply_base_migration()

        assert result.version == BASE_MIGRATION_VERSION
        assert result.status is MigrationStatus.SUCCEEDED
        assert _schema_names(connection) >= {
            "business",
            "semantic",
            "runtime",
            "governance",
            "evaluation",
            "knowledge",
        }
        assert _scalar(connection, "SELECT COUNT(*) FROM semantic.metrics WHERE metric_id = 'revenue'") == 1
        assert _scalar(connection, "SELECT COUNT(*) FROM runtime.sessions WHERE session_id = 'sess_demo_revenue_2026_h1'") == 1
        assert _scalar(connection, "SELECT COUNT(*) FROM knowledge.documents WHERE source_id = 'rag_revenue_policy_2026'") == 1
        assert _scalar(connection, "SELECT COUNT(*) FROM governance.access_policies WHERE policy_id = 'pol_customers_customer_id_p0'") == 1

        trace_store = PostgresTraceLinkedRecordStore(PsycopgTraceLinkedRecordConnection(connection))
        trace_records = trace_store.get_records(DEMO_COMPLETED_QUERY_TRACE_ID)
        assert tuple(record.record_type.value for record in trace_records) == (
            "message",
            "query_result",
            "agent_trace",
            "audit_event",
            "eval_score",
        )

        history_store = PostgresRuntimeQueryHistoryStore(PsycopgRuntimeQueryHistoryConnection(connection))
        history_records = history_store.list_by_session("sess_demo_revenue_2026_h1", limit=5)
        assert history_records
        assert history_records[0].trace_id == DEMO_COMPLETED_QUERY_TRACE_ID

        _assert_duplicate_query_result_trace_id_fails(connection)
    finally:
        _close_quietly(connection)


def _schema_names(connection: Any) -> set[str]:
    cursor = connection.execute(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name IN ('business', 'semantic', 'runtime', 'governance', 'evaluation', 'knowledge')
        """
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _scalar(connection: Any, sql: str) -> int:
    cursor = connection.execute(sql)
    row = cursor.fetchone()
    if row is None:
        raise AssertionError(f"query returned no row: {sql}")
    return int(row[0])


def _assert_duplicate_query_result_trace_id_fails(connection: Any) -> None:
    with pytest.raises(Exception):
        connection.execute(
            """
            INSERT INTO runtime.query_results (
                query_result_id,
                trace_id,
                message_id,
                sql_hash,
                table_result,
                chart_spec,
                created_at
            )
            VALUES (
                'qr_duplicate_trace_check',
                'trc_demo_revenue_2026_h1',
                'msg_demo_revenue_question',
                'sqlhash_duplicate_trace_check',
                '{}'::jsonb,
                NULL,
                '2026-06-25T00:00:08Z'
            )
            """
        )
    connection.rollback()


def _close_quietly(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if not callable(close):
        return
    close()
