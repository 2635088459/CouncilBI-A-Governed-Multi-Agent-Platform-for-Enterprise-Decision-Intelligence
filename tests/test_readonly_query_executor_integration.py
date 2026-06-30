import os
from uuid import uuid4

import pytest

from chatbi.governance import ReadOnlyQueryExecutor, ReadOnlyQueryStatus
from chatbi.history.request_metadata import connect_psycopg


def test_readonly_query_executor_live_selects_business_rows() -> None:
    database_url = os.environ.get("DATABASE_URL")
    readonly_database_url = os.environ.get("CHATBI_READONLY_DATABASE_URL")
    if not database_url or not readonly_database_url:
        pytest.skip(
            "DATABASE_URL and CHATBI_READONLY_DATABASE_URL are required for live "
            "read-only query integration."
        )

    table_name = f"readonly_executor_probe_{uuid4().hex[:16]}"
    qualified_table_name = f"business.{table_name}"
    writer_connection = connect_psycopg(database_url)
    try:
        writer_connection.execute(
            f"""
            CREATE TABLE {qualified_table_name} (
                month TEXT NOT NULL,
                revenue INTEGER NOT NULL
            )
            """
        )
        writer_connection.execute(
            f"""
            INSERT INTO {qualified_table_name} (month, revenue)
            VALUES ('2026-01', 1000), ('2026-02', 1120)
            """
        )
        writer_connection.execute(f"GRANT SELECT ON {qualified_table_name} TO chatbi_readonly")
        writer_connection.commit()

        executor = ReadOnlyQueryExecutor(connect_psycopg, max_rows=10)

        result = executor.execute(
            readonly_database_url,
            f"SELECT month, revenue FROM {qualified_table_name} ORDER BY month",
        )

        assert result.status is ReadOnlyQueryStatus.SUCCEEDED
        assert result.table_result is not None
        assert result.table_result.columns == ("month", "revenue")
        assert result.table_result.rows == (
            {"month": "2026-01", "revenue": 1000},
            {"month": "2026-02", "revenue": 1120},
        )
    finally:
        writer_connection.execute(f"DROP TABLE IF EXISTS {qualified_table_name}")
        writer_connection.commit()
        writer_connection.close()
