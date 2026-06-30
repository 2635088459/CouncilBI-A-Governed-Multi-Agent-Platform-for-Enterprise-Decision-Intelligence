from chatbi.analytics import AnalyticsGrain, AnalyticsRequest, AnalyticsService
from chatbi.analytics_repository import InMemoryAnalyticsRepository
from chatbi.analytics_worker import AnalyticsWorker, AnalyticsWorkerError
from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRequest,
    AsyncTaskStatus,
    InMemoryWorkerHandoffQueue,
)


def test_analytics_worker_processes_queued_request() -> None:
    repository = InMemoryAnalyticsRepository()
    worker = AnalyticsWorker(AnalyticsService(repository))
    task = worker.enqueue_analytics_request(_request("tr_worker_ok"))

    result = worker.process_task(task.task_id)

    assert result.task.status is AsyncTaskStatus.SUCCEEDED
    assert result.task.result["method"] == "rolling_zscore_linear_forecast"
    assert result.task.result["forecast_points"]
    assert result.result.forecast_points
    assert repository.result_by_trace_id("tr_worker_ok") is not None


def test_analytics_worker_rejects_missing_task() -> None:
    worker = AnalyticsWorker(AnalyticsService(InMemoryAnalyticsRepository()))

    try:
        worker.process_task("task_missing")
    except AnalyticsWorkerError as exc:
        assert "was not found" in str(exc)
    else:
        raise AssertionError("Expected missing analytics task to raise")


def test_analytics_worker_rejects_non_analytics_task() -> None:
    queue = InMemoryWorkerHandoffQueue()
    task = queue.enqueue(
        AsyncTaskRequest(
            trace_id="tr_wrong_kind",
            kind=AsyncTaskKind.INDEXING,
            payload={"request": _request("tr_wrong_kind")},
        )
    )
    worker = AnalyticsWorker(AnalyticsService(InMemoryAnalyticsRepository()), queue=queue)

    try:
        worker.process_task(task.task_id)
    except AnalyticsWorkerError as exc:
        assert "not an analytics task" in str(exc)
    else:
        raise AssertionError("Expected non-analytics task to raise")


def test_analytics_worker_marks_task_failed_when_payload_is_invalid() -> None:
    queue = InMemoryWorkerHandoffQueue()
    task = queue.enqueue(
        AsyncTaskRequest(
            trace_id="tr_bad_payload",
            kind=AsyncTaskKind.ANALYTICS,
            payload={},
        )
    )
    worker = AnalyticsWorker(AnalyticsService(InMemoryAnalyticsRepository()), queue=queue)

    try:
        worker.process_task(task.task_id)
    except AnalyticsWorkerError:
        failed_task = queue.get(task.task_id)
        assert failed_task is not None
        assert failed_task.status is AsyncTaskStatus.FAILED
        assert "request is required" in (failed_task.error_message or "")
    else:
        raise AssertionError("Expected invalid analytics payload to raise")


def test_analytics_worker_processes_json_shaped_request_payload() -> None:
    queue = InMemoryWorkerHandoffQueue()
    task = queue.enqueue(
        AsyncTaskRequest(
            trace_id="tr_json_payload",
            kind=AsyncTaskKind.ANALYTICS,
            payload={
                "request": {
                    "trace_id": "tr_json_payload",
                    "metric_id": "revenue",
                    "semantic_version_id": "sem_v2",
                    "time_column": "date",
                    "value_column": "revenue",
                    "grain": "day",
                    "rows": (
                        {"date": "2026-06-01", "revenue": 100.0},
                        {"date": "2026-06-02", "revenue": 105.0},
                        {"date": "2026-06-03", "revenue": 110.0},
                    ),
                    "analysis_options": {"horizon": 2, "anomaly_z_threshold": 3.0},
                }
            },
        )
    )
    repository = InMemoryAnalyticsRepository()
    worker = AnalyticsWorker(AnalyticsService(repository), queue=queue)

    result = worker.process_task(task.task_id)

    assert result.task.status is AsyncTaskStatus.SUCCEEDED
    assert len(result.result.forecast_points) == 2
    assert repository.result_by_trace_id("tr_json_payload") is not None


def test_analytics_worker_can_write_timed_out_final_status() -> None:
    worker = AnalyticsWorker(AnalyticsService(InMemoryAnalyticsRepository()))
    task = worker.enqueue_analytics_request(_request("tr_worker_timeout"))

    timed_out = worker.mark_timed_out(task.task_id, "analytics exceeded timeout")

    assert timed_out.status is AsyncTaskStatus.TIMED_OUT
    assert timed_out.error_message == "analytics exceeded timeout"


def _request(trace_id: str) -> AnalyticsRequest:
    return AnalyticsRequest(
        trace_id=trace_id,
        metric_id="revenue",
        semantic_version_id="sem_v2",
        time_column="date",
        value_column="revenue",
        grain=AnalyticsGrain.DAY,
        rows=(
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
            {"date": "2026-06-03", "revenue": 110.0},
            {"date": "2026-06-04", "revenue": 115.0},
        ),
    )
