"""Prometheus runtime metrics for spec 10.

The application records request samples while it handles traffic. This module
turns those samples into the small Prometheus text surface required by the
runtime probes: request count, error count, and latency summary fields.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from chatbi.observability import RuntimeRequestSample


@dataclass(frozen=True, slots=True)
class RuntimeMetricsSnapshot:
    request_count: int
    error_count: int
    latency_count: int
    latency_sum_ms: int
    latency_max_ms: int


def runtime_metrics_snapshot(
    samples: Sequence[RuntimeRequestSample],
) -> RuntimeMetricsSnapshot:
    latencies = tuple(sample.latency_ms for sample in samples)
    return RuntimeMetricsSnapshot(
        request_count=len(samples),
        error_count=sum(1 for sample in samples if not sample.succeeded),
        latency_count=len(latencies),
        latency_sum_ms=sum(latencies),
        latency_max_ms=max(latencies) if latencies else 0,
    )


def render_runtime_metrics(snapshot: RuntimeMetricsSnapshot | None = None) -> str:
    active_snapshot = snapshot or RuntimeMetricsSnapshot(
        request_count=0,
        error_count=0,
        latency_count=0,
        latency_sum_ms=0,
        latency_max_ms=0,
    )
    return "\n".join(
        (
            "# HELP chatbi_api_request_count_total Total accepted API requests recorded by the application.",
            "# TYPE chatbi_api_request_count_total counter",
            f"chatbi_api_request_count_total {active_snapshot.request_count}",
            "# HELP chatbi_api_error_count_total Total API requests completed with an error status.",
            "# TYPE chatbi_api_error_count_total counter",
            f"chatbi_api_error_count_total {active_snapshot.error_count}",
            "# HELP chatbi_api_request_latency_ms Request latency summary in milliseconds.",
            "# TYPE chatbi_api_request_latency_ms summary",
            f"chatbi_api_request_latency_ms_count {active_snapshot.latency_count}",
            f"chatbi_api_request_latency_ms_sum {active_snapshot.latency_sum_ms}",
            f"chatbi_api_request_latency_ms_max {active_snapshot.latency_max_ms}",
        )
    )
