"""Worker adapter for queued RAG v2 indexing jobs.

The RAG service owns indexing behavior. The worker owns async task lifecycle:
enqueue, mark running, call the service, and persist succeeded or failed task
status for callers that poll task state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRecord,
    AsyncTaskRequest,
    InMemoryWorkerHandoffQueue,
    WorkerHandoffQueue,
)
from chatbi.rag import IndexJob, IndexJobStatus
from chatbi.rag_indexing import ChunkSettings
from chatbi.rag_service import InMemoryRagService


@dataclass(frozen=True, slots=True)
class RagIndexWorkerResult:
    task: AsyncTaskRecord
    job: IndexJob


class RagIndexWorker:
    """Run queued RAG index jobs through the shared async-task queue."""

    def __init__(
        self,
        rag_service: InMemoryRagService,
        queue: WorkerHandoffQueue | None = None,
    ) -> None:
        self._rag_service = rag_service
        self._queue = queue or InMemoryWorkerHandoffQueue()

    @property
    def queue(self) -> WorkerHandoffQueue:
        return self._queue

    def enqueue_index_job(self, trace_id: str, job_id: str) -> AsyncTaskRecord:
        if not job_id.strip():
            raise ValueError("job_id is required")
        return self._queue.enqueue(
            AsyncTaskRequest(
                trace_id=trace_id,
                kind=AsyncTaskKind.INDEXING,
                payload={"job_id": job_id},
            )
        )

    def process_task(
        self,
        task_id: str,
        chunk_settings: ChunkSettings = ChunkSettings(),
    ) -> RagIndexWorkerResult:
        task = self._require_indexing_task(task_id)
        self._queue.mark_running(task.task_id)

        try:
            job = self._rag_service.run_index_job(
                _payload_string(task.payload, "job_id"),
                chunk_settings=chunk_settings,
            )
        except Exception as exc:
            failed_task = self._queue.mark_failed(task.task_id, str(exc))
            raise RagIndexWorkerError(f"RAG index task {task.task_id} failed") from exc

        if job.status is IndexJobStatus.FAILED:
            failed_task = self._queue.mark_failed(
                task.task_id,
                job.error_message or "RAG index job failed",
            )
            return RagIndexWorkerResult(task=failed_task, job=job)

        succeeded_task = self._queue.mark_succeeded(
            task.task_id,
            result={
                "job_id": job.job_id,
                "document_id": job.document_id,
                "status": job.status.value,
            },
        )
        return RagIndexWorkerResult(task=succeeded_task, job=job)

    def _require_indexing_task(self, task_id: str) -> AsyncTaskRecord:
        task = self._queue.get(task_id)
        if task is None:
            raise RagIndexWorkerError(f"RAG index task {task_id} was not found")
        if task.kind is not AsyncTaskKind.INDEXING:
            raise RagIndexWorkerError(f"Task {task_id} is not a RAG indexing task")
        return task


class RagIndexWorkerError(RuntimeError):
    """Raised when a queued RAG indexing task cannot be processed."""


def _payload_string(payload: Mapping[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required in RAG worker payload")
    return value
