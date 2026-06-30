from datetime import datetime, timezone

from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRequest,
    AsyncTaskStatus,
    InMemoryWorkerHandoffQueue,
)
from chatbi.rag import IndexDocumentRequest, IndexJobStatus
from chatbi.rag_indexing import ChunkSettings
from chatbi.rag_service import InMemoryRagService
from chatbi.rag_worker import RagIndexWorker, RagIndexWorkerError


PUBLISHED_AT = datetime(2026, 6, 1, tzinfo=timezone.utc)


def make_long_index_request() -> IndexDocumentRequest:
    return IndexDocumentRequest(
        document_id="doc_long_001",
        source="release-notes",
        title="Long release note",
        document_type="release_note",
        published_at=PUBLISHED_AT,
        business_tags=("revenue",),
        permission_tags=("sales",),
        text="x" * 50_001,
    )


def test_rag_index_worker_processes_queued_index_job() -> None:
    service = InMemoryRagService()
    queued_job = service.index_document(make_long_index_request())
    worker = RagIndexWorker(service)
    task = worker.enqueue_index_job(
        trace_id="trc_rag_worker",
        job_id=queued_job.job_id,
    )

    result = worker.process_task(
        task.task_id,
        chunk_settings=ChunkSettings(token_limit=1000, overlap=0),
    )

    assert result.task.status is AsyncTaskStatus.SUCCEEDED
    assert result.task.result["job_id"] == queued_job.job_id
    assert result.task.result["status"] == "succeeded"
    assert result.job.status is IndexJobStatus.SUCCEEDED
    assert service.state().indexed_chunk_count == 1


def test_rag_index_worker_rejects_missing_task() -> None:
    worker = RagIndexWorker(InMemoryRagService())

    try:
        worker.process_task("task_missing")
    except RagIndexWorkerError as exc:
        assert "was not found" in str(exc)
    else:
        raise AssertionError("Expected missing RAG worker task to raise")


def test_rag_index_worker_rejects_non_indexing_task() -> None:
    queue = InMemoryWorkerHandoffQueue()
    task = queue.enqueue(
        AsyncTaskRequest(
            trace_id="trc_wrong_kind",
            kind=AsyncTaskKind.ANALYTICS,
            payload={"job_id": "rag_job_wrong"},
        )
    )
    worker = RagIndexWorker(InMemoryRagService(), queue=queue)

    try:
        worker.process_task(task.task_id)
    except RagIndexWorkerError as exc:
        assert "not a RAG indexing task" in str(exc)
    else:
        raise AssertionError("Expected non-indexing task to raise")


def test_rag_index_worker_marks_task_failed_when_payload_is_invalid() -> None:
    queue = InMemoryWorkerHandoffQueue()
    task = queue.enqueue(
        AsyncTaskRequest(
            trace_id="trc_bad_payload",
            kind=AsyncTaskKind.INDEXING,
            payload={},
        )
    )
    worker = RagIndexWorker(InMemoryRagService(), queue=queue)

    try:
        worker.process_task(task.task_id)
    except RagIndexWorkerError:
        failed_task = queue.get(task.task_id)
        assert failed_task is not None
        assert failed_task.status is AsyncTaskStatus.FAILED
        assert "job_id is required" in (failed_task.error_message or "")
    else:
        raise AssertionError("Expected invalid RAG worker payload to raise")
