"""FR-FV03-043 (Spec 4.7): durable observability storage otherwise grows
without bound. Mirrors test_file_archival_admin_and_scheduling.py's
test_retention_sweep_runs_at_least_once_shortly_after_app_startup — a
short interval override stands in for the real schedule so the test
window stays bounded, and the sweep must have run by the time the
lifespan's startup phase completes.
"""

import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.application.app import ChatBIApplication
from chatbi.observability import (
    InMemoryObservabilityStore,
    ObservabilitySpan,
    TraceRecorder,
    TraceSpanName,
    TraceSpanStatus,
)
from chatbi.observability_logs import (
    InMemoryObservabilityLogStore,
    LogLevel,
    ObservabilityLogger,
    ObservabilityLogRecord,
)


def test_observability_retention_sweep_prunes_stale_records_and_spans_shortly_after_startup() -> None:
    log_store = InMemoryObservabilityLogStore()
    trace_store = InMemoryObservabilityStore()
    now = datetime.now(timezone.utc)
    log_store.add(
        ObservabilityLogRecord(
            trace_id="trc_old",
            level=LogLevel.INFO,
            message="old",
            endpoint="/api/v1/chat/query",
            user_id="u_001",
            recorded_at=now - timedelta(days=40),
        )
    )
    log_store.add(
        ObservabilityLogRecord(
            trace_id="trc_recent",
            level=LogLevel.INFO,
            message="recent",
            endpoint="/api/v1/chat/query",
            user_id="u_001",
            recorded_at=now,
        )
    )
    trace_store.add_span(
        ObservabilitySpan(
            trace_id="trc_old",
            span_name=TraceSpanName.REQUEST_RECEIVED,
            status=TraceSpanStatus.SUCCEEDED,
            occurred_at=now - timedelta(days=40),
        )
    )
    trace_store.add_span(
        ObservabilitySpan(
            trace_id="trc_recent",
            span_name=TraceSpanName.REQUEST_RECEIVED,
            status=TraceSpanStatus.SUCCEEDED,
            occurred_at=now,
        )
    )
    application = ChatBIApplication(
        trace_recorder=TraceRecorder(store=trace_store),
        observability_logger=ObservabilityLogger(store=log_store),
    )
    app = create_app(application=application, retention_sweep_interval_seconds=1000.0)

    with TestClient(app):
        time.sleep(0.3)

    remaining_logs = {record.trace_id for record in log_store.list_all()}
    remaining_spans = {span.trace_id for span in trace_store.list_all()}
    assert remaining_logs == {"trc_recent"}
    assert remaining_spans == {"trc_recent"}
