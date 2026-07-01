from datetime import datetime, timezone

from chatbi.observability import RuntimeRequestSample
from chatbi.runtime_metrics import render_runtime_metrics, runtime_metrics_snapshot


NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_runtime_metrics_snapshot_counts_requests_errors_and_latency() -> None:
    snapshot = runtime_metrics_snapshot(
        (
            RuntimeRequestSample(
                trace_id="trc_metrics_ok",
                endpoint="/api/v1/chat/query",
                status_code=200,
                latency_ms=12,
                occurred_at=NOW,
            ),
            RuntimeRequestSample(
                trace_id="trc_metrics_error",
                endpoint="/api/v1/chat/query",
                status_code=500,
                latency_ms=35,
                occurred_at=NOW,
            ),
        )
    )

    assert snapshot.request_count == 2
    assert snapshot.error_count == 1
    assert snapshot.latency_count == 2
    assert snapshot.latency_sum_ms == 47
    assert snapshot.latency_max_ms == 35


def test_render_runtime_metrics_exposes_spec_required_metric_names() -> None:
    text = render_runtime_metrics()

    assert "chatbi_api_request_count_total 0" in text
    assert "chatbi_api_error_count_total 0" in text
    assert "chatbi_api_request_latency_ms_count 0" in text
    assert "chatbi_api_request_latency_ms_sum 0" in text
