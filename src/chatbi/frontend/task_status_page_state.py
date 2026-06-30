"""Task Status page state for long-running ChatBI work.

The API client knows how to fetch one task. This store keeps the small amount
of page state needed by the UI: which task id is selected, whether a lookup is
running, and the latest render-ready status.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.task_status_state import TaskStatusViewModel


@dataclass(frozen=True, slots=True)
class TaskStatusPageState:
    context: FrontendUserContext
    task_id: str | None = None
    current_status: TaskStatusViewModel | None = None
    is_loading: bool = False
    error_message: str | None = None

    @property
    def has_task(self) -> bool:
        return self.current_status is not None


class TaskStatusApiPort(Protocol):
    def load_task_status(
        self,
        context: FrontendUserContext,
        task_id: str,
    ) -> TaskStatusViewModel:
        """Load one long-running task status from the Backend API."""
        ...


class TaskStatusPageStore:
    """Small in-memory store for the Task Status page."""

    def __init__(
        self,
        context: FrontendUserContext,
        api_client: TaskStatusApiPort,
    ) -> None:
        self._api_client = api_client
        self._state = TaskStatusPageState(context=context)

    @property
    def state(self) -> TaskStatusPageState:
        return self._state

    def set_task_id(self, task_id: str) -> TaskStatusPageState:
        normalized_task_id = _normalize_task_id(task_id)
        self._state = replace(
            self._state,
            task_id=normalized_task_id,
            error_message=None,
        )
        return self._state

    def load_current_task(self) -> TaskStatusPageState:
        if self._state.task_id is None:
            self._state = replace(
                self._state,
                error_message="Task id is required.",
            )
            return self._state

        return self.load_task(self._state.task_id)

    def load_task(self, task_id: str) -> TaskStatusPageState:
        normalized_task_id = _normalize_task_id(task_id)
        self._state = replace(
            self._state,
            task_id=normalized_task_id,
            is_loading=True,
            error_message=None,
        )

        try:
            status = self._api_client.load_task_status(
                context=self._state.context,
                task_id=normalized_task_id,
            )
        except ValueError as exc:
            self._state = replace(
                self._state,
                is_loading=False,
                error_message=str(exc),
            )
            return self._state

        self._state = replace(
            self._state,
            current_status=status,
            is_loading=False,
            error_message=None,
        )
        return self._state


def _normalize_task_id(task_id: str) -> str:
    normalized = task_id.strip()
    if not normalized:
        raise ValueError("Task id is required.")
    return normalized
