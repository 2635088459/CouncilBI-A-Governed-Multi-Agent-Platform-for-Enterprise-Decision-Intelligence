"""Worker handoff contracts for long-running orchestration tasks.

The v2 orchestration spec requires async analytics or indexing work to create a
task id. This module keeps that boundary small: the orchestrator submits a typed
task request, receives a task id, and a worker can later consume the record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4


class AsyncTaskKind(StrEnum):
    ANALYTICS = "analytics"
    INDEXING = "indexing"


class AsyncTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


def new_task_id() -> str:
    return f"task_{uuid4().hex}"


def _empty_payload() -> Mapping[str, Any]:
    return {}


def _empty_result() -> Mapping[str, Any]:
    return {}


def _empty_tasks() -> dict[str, "AsyncTaskRecord"]:
    return {}


@dataclass(frozen=True, slots=True)
class AsyncTaskRequest:
    trace_id: str
    kind: AsyncTaskKind
    payload: Mapping[str, Any] = field(default_factory=_empty_payload)

    def __post_init__(self) -> None:
        if not self.trace_id.strip():
            raise ValueError("trace_id is required")


@dataclass(frozen=True, slots=True)
class AsyncTaskRecord:
    task_id: str
    trace_id: str
    kind: AsyncTaskKind
    status: AsyncTaskStatus
    payload: Mapping[str, Any]
    result: Mapping[str, Any] = field(default_factory=_empty_result)
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id.startswith("task_"):
            raise ValueError("task_id must start with task_")
        if self.status in (AsyncTaskStatus.FAILED, AsyncTaskStatus.TIMED_OUT) and not (
            self.error_message or ""
        ).strip():
            raise ValueError("failed or timed_out task must include error_message")
        if (
            self.status not in (AsyncTaskStatus.FAILED, AsyncTaskStatus.TIMED_OUT)
            and self.error_message is not None
        ):
            raise ValueError("only failed or timed_out tasks may include error_message")


class WorkerHandoffQueue(Protocol):
    def enqueue(self, request: AsyncTaskRequest) -> AsyncTaskRecord:
        """Create a task id and queue a long-running worker task."""
        ...

    def get(self, task_id: str) -> AsyncTaskRecord | None:
        """Return one queued task by task id."""
        ...

    def mark_running(self, task_id: str) -> AsyncTaskRecord:
        """Persist that a worker has started processing one task."""
        ...

    def mark_succeeded(
        self,
        task_id: str,
        result: Mapping[str, Any] | None = None,
    ) -> AsyncTaskRecord:
        """Persist successful completion for one task."""
        ...

    def mark_failed(self, task_id: str, error_message: str) -> AsyncTaskRecord:
        """Persist failed completion for one task."""
        ...

    def mark_timed_out(self, task_id: str, error_message: str) -> AsyncTaskRecord:
        """Persist timeout completion for one task."""
        ...

    def list_by_trace_id(self, trace_id: str) -> tuple[AsyncTaskRecord, ...]:
        """Return queued tasks related to one orchestration trace."""
        ...


@dataclass(slots=True)
class InMemoryWorkerHandoffQueue:
    """Redis-queue-shaped handoff implementation for tests and local runs."""

    _tasks: dict[str, AsyncTaskRecord] = field(default_factory=_empty_tasks)

    def enqueue(self, request: AsyncTaskRequest) -> AsyncTaskRecord:
        record = AsyncTaskRecord(
            task_id=new_task_id(),
            trace_id=request.trace_id,
            kind=request.kind,
            status=AsyncTaskStatus.QUEUED,
            payload=request.payload,
        )
        self._tasks[record.task_id] = record
        return record

    def get(self, task_id: str) -> AsyncTaskRecord | None:
        return self._tasks.get(task_id)

    def mark_running(self, task_id: str) -> AsyncTaskRecord:
        return self._replace_status(task_id, AsyncTaskStatus.RUNNING)

    def mark_succeeded(
        self,
        task_id: str,
        result: Mapping[str, Any] | None = None,
    ) -> AsyncTaskRecord:
        return self._replace_status(
            task_id,
            AsyncTaskStatus.SUCCEEDED,
            result=result or {},
        )

    def mark_failed(self, task_id: str, error_message: str) -> AsyncTaskRecord:
        if not error_message.strip():
            raise ValueError("error_message is required")
        return self._replace_status(
            task_id,
            AsyncTaskStatus.FAILED,
            error_message=error_message,
        )

    def mark_timed_out(self, task_id: str, error_message: str) -> AsyncTaskRecord:
        if not error_message.strip():
            raise ValueError("error_message is required")
        return self._replace_status(
            task_id,
            AsyncTaskStatus.TIMED_OUT,
            error_message=error_message,
        )

    def list_by_trace_id(self, trace_id: str) -> tuple[AsyncTaskRecord, ...]:
        return tuple(task for task in self._tasks.values() if task.trace_id == trace_id)

    def _replace_status(
        self,
        task_id: str,
        status: AsyncTaskStatus,
        result: Mapping[str, Any] | None = None,
        error_message: str | None = None,
    ) -> AsyncTaskRecord:
        record = self._tasks.get(task_id)
        if record is None:
            raise KeyError(f"Task {task_id} was not found.")
        updated = replace(
            record,
            status=status,
            result=result or {},
            error_message=error_message,
        )
        self._tasks[task_id] = updated
        return updated
