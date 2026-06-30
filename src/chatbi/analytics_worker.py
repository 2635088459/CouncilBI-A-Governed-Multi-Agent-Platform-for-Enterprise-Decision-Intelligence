"""Worker adapter for queued analytics v2 jobs.

The analytics service owns validation, anomaly detection, forecasting, and
persistence. The worker only owns async lifecycle: enqueue, mark running, call
the service, and write a final task status.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from chatbi.analytics import (
    AnalyticsGrain,
    AnalyticsOptions,
    AnalyticsRequest,
    AnalyticsResult,
    AnalyticsService,
    result_to_dict,
)
from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRecord,
    AsyncTaskRequest,
    InMemoryWorkerHandoffQueue,
    WorkerHandoffQueue,
)


@dataclass(frozen=True, slots=True)
class AnalyticsWorkerResult:
    task: AsyncTaskRecord
    result: AnalyticsResult


class AnalyticsWorker:
    """Run queued analytics requests through the shared async-task queue."""

    def __init__(
        self,
        analytics_service: AnalyticsService,
        queue: WorkerHandoffQueue | None = None,
    ) -> None:
        self._analytics_service = analytics_service
        self._queue = queue or InMemoryWorkerHandoffQueue()

    @property
    def queue(self) -> WorkerHandoffQueue:
        return self._queue

    def enqueue_analytics_request(self, request: AnalyticsRequest) -> AsyncTaskRecord:
        return self._queue.enqueue(
            AsyncTaskRequest(
                trace_id=request.trace_id,
                kind=AsyncTaskKind.ANALYTICS,
                payload={"request": request},
            )
        )

    def process_task(self, task_id: str) -> AnalyticsWorkerResult:
        task = self._require_analytics_task(task_id)
        self._queue.mark_running(task.task_id)

        try:
            request = _payload_request(task.payload)
            result = self._analytics_service.analyze(request)
        except Exception as exc:
            failed_task = self._queue.mark_failed(task.task_id, str(exc))
            raise AnalyticsWorkerError(f"Analytics task {failed_task.task_id} failed") from exc

        succeeded_task = self._queue.mark_succeeded(
            task.task_id,
            result=result_to_dict(result),
        )
        return AnalyticsWorkerResult(task=succeeded_task, result=result)

    def mark_timed_out(self, task_id: str, error_message: str) -> AsyncTaskRecord:
        task = self._require_analytics_task(task_id)
        return self._queue.mark_timed_out(task.task_id, error_message)

    def _require_analytics_task(self, task_id: str) -> AsyncTaskRecord:
        task = self._queue.get(task_id)
        if task is None:
            raise AnalyticsWorkerError(f"Analytics task {task_id} was not found")
        if task.kind is not AsyncTaskKind.ANALYTICS:
            raise AnalyticsWorkerError(f"Task {task_id} is not an analytics task")
        return task


class AnalyticsWorkerError(RuntimeError):
    """Raised when a queued analytics task cannot be processed."""


def _payload_request(payload: Mapping[str, object]) -> AnalyticsRequest:
    value = payload.get("request")
    if isinstance(value, AnalyticsRequest):
        return value
    if isinstance(value, Mapping):
        request = cast(Mapping[str, object], value)
        options_value = request.get("analysis_options")
        options = (
            _payload_options(cast(Mapping[str, object], options_value))
            if isinstance(options_value, Mapping)
            else AnalyticsOptions()
        )
        rows_value = request.get("rows")
        if not isinstance(rows_value, tuple | list):
            raise ValueError("rows is required in analytics worker payload")
        rows = cast(Sequence[object], rows_value)
        return AnalyticsRequest(
            trace_id=_payload_string(request, "trace_id"),
            metric_id=_payload_string(request, "metric_id"),
            semantic_version_id=_payload_string(request, "semantic_version_id"),
            time_column=_payload_string(request, "time_column"),
            value_column=_payload_string(request, "value_column"),
            grain=AnalyticsGrain(_payload_string(request, "grain")),
            rows=tuple(_payload_row(row) for row in rows),
            analysis_options=options,
        )
    raise ValueError("request is required in analytics worker payload")


def _payload_options(payload: Mapping[str, object]) -> AnalyticsOptions:
    return AnalyticsOptions(
        horizon=_payload_int(payload, "horizon", default=3),
        anomaly_z_threshold=_payload_float(
            payload,
            "anomaly_z_threshold",
            default=3.0,
        ),
    )


def _payload_row(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("analytics rows must be objects")
    return dict(cast(Mapping[str, object], value))


def _payload_string(payload: Mapping[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required in analytics worker payload")
    return value


def _payload_int(payload: Mapping[str, object], field_name: str, default: int) -> int:
    value = payload.get(field_name, default)
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _payload_float(payload: Mapping[str, object], field_name: str, default: float) -> float:
    value = payload.get(field_name, default)
    if not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)
