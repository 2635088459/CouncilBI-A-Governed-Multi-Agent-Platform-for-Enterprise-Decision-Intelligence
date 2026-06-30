import os
from uuid import uuid4

import pytest

from chatbi.core.contracts import Locale, UserRole
from chatbi.history.request_metadata import (
    RequestFinalStatus,
    RequestMetadataRecord,
    connect_psycopg,
    postgres_request_metadata_store_from_psycopg,
)


def test_postgres_request_metadata_live_insert_update_select() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for live PostgreSQL metadata integration.")

    connection = connect_psycopg(database_url)
    store = postgres_request_metadata_store_from_psycopg(connection)
    store.initialize_schema()
    trace_id = f"tr_live_{uuid4().hex[:16]}"
    record = RequestMetadataRecord(
        trace_id=trace_id,
        request_id=f"req_live_{uuid4().hex[:16]}",
        session_id=f"ses_live_{uuid4().hex[:16]}",
        user_id="u_live",
        role=UserRole.BUSINESS_USER,
        locale=Locale.EN,
        question="Show revenue trend.",
    )

    store.save_accepted(record)
    updated = store.mark_succeeded(trace_id)
    selected = store.get(trace_id)
    connection.close()

    assert updated.status is RequestFinalStatus.SUCCEEDED
    assert selected is not None
    assert selected.trace_id == trace_id
    assert selected.status is RequestFinalStatus.SUCCEEDED
    assert selected.request_id == record.request_id
    assert selected.finished_at is not None
