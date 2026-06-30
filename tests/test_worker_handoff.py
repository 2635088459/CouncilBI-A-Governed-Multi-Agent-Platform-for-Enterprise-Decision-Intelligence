import pytest

from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRecord,
    AsyncTaskRequest,
    AsyncTaskStatus,
    InMemoryWorkerHandoffQueue,
)


def test_worker_handoff_creates_task_id_for_async_analytics() -> None:
    queue = InMemoryWorkerHandoffQueue()
    request = AsyncTaskRequest(
        trace_id="tr_analytics_001",
        kind=AsyncTaskKind.ANALYTICS,
        payload={"metric": "revenue", "horizon_days": 30},
    )

    record = queue.enqueue(request)

    assert record.task_id.startswith("task_")
    assert record.trace_id == "tr_analytics_001"
    assert record.kind is AsyncTaskKind.ANALYTICS
    assert record.status is AsyncTaskStatus.QUEUED
    assert queue.get(record.task_id) == record


def test_worker_handoff_creates_task_id_for_indexing() -> None:
    queue = InMemoryWorkerHandoffQueue()
    request = AsyncTaskRequest(
        trace_id="tr_indexing_001",
        kind=AsyncTaskKind.INDEXING,
        payload={"source_id": "doc_001"},
    )

    record = queue.enqueue(request)

    assert record.task_id.startswith("task_")
    assert record.kind is AsyncTaskKind.INDEXING
    assert queue.list_by_trace_id("tr_indexing_001") == (record,)


def test_worker_handoff_marks_task_running_and_succeeded() -> None:
    queue = InMemoryWorkerHandoffQueue()
    record = queue.enqueue(
        AsyncTaskRequest(
            trace_id="tr_indexing_status",
            kind=AsyncTaskKind.INDEXING,
            payload={"source_id": "doc_001"},
        )
    )

    running = queue.mark_running(record.task_id)
    succeeded = queue.mark_succeeded(
        record.task_id,
        result={"document_id": "doc_001", "chunk_count": 3},
    )

    assert running.status is AsyncTaskStatus.RUNNING
    assert succeeded.status is AsyncTaskStatus.SUCCEEDED
    assert succeeded.result == {"document_id": "doc_001", "chunk_count": 3}
    assert succeeded.error_message is None
    assert queue.get(record.task_id) == succeeded


def test_worker_handoff_marks_task_failed_with_error_message() -> None:
    queue = InMemoryWorkerHandoffQueue()
    record = queue.enqueue(
        AsyncTaskRequest(
            trace_id="tr_indexing_failed",
            kind=AsyncTaskKind.INDEXING,
            payload={"source_id": "doc_001"},
        )
    )

    failed = queue.mark_failed(record.task_id, error_message="embedding service unavailable")

    assert failed.status is AsyncTaskStatus.FAILED
    assert failed.error_message == "embedding service unavailable"
    assert failed.result == {}


def test_worker_handoff_rejects_missing_task_status_update() -> None:
    queue = InMemoryWorkerHandoffQueue()

    with pytest.raises(KeyError, match="task_missing"):
        queue.mark_running("task_missing")


def test_async_task_request_requires_trace_id() -> None:
    with pytest.raises(ValueError, match="trace_id"):
        AsyncTaskRequest(
            trace_id="",
            kind=AsyncTaskKind.ANALYTICS,
        )


def test_async_task_record_requires_task_id_prefix() -> None:
    with pytest.raises(ValueError, match="task_id"):
        AsyncTaskRecord(
            task_id="bad_001",
            trace_id="tr_analytics_001",
            kind=AsyncTaskKind.ANALYTICS,
            status=AsyncTaskStatus.QUEUED,
            payload={},
        )


def test_failed_async_task_record_requires_error_message() -> None:
    with pytest.raises(ValueError, match="error_message"):
        AsyncTaskRecord(
            task_id="task_failed",
            trace_id="tr_analytics_001",
            kind=AsyncTaskKind.ANALYTICS,
            status=AsyncTaskStatus.FAILED,
            payload={},
        )
