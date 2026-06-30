"""Task status view model for long-running ChatBI work.

The backend exposes worker-oriented statuses such as ``succeeded``. The
frontend spec wants user-facing statuses such as ``completed``. This module is
the adapter between those two vocabularies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, cast

from chatbi.core.contracts import Locale
from chatbi.frontend.i18n import TranslationKey, translate


class UiTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class TaskStatusViewModel:
    task_id: str
    trace_id: str
    kind: str
    status: UiTaskStatus
    label: str
    result: Mapping[str, Any]
    error_message: str | None

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            UiTaskStatus.PARTIAL,
            UiTaskStatus.FAILED,
            UiTaskStatus.COMPLETED,
        }

    @property
    def is_warning(self) -> bool:
        return self.status is UiTaskStatus.PARTIAL


def build_task_status_view_model(
    raw_task: Mapping[str, Any],
    locale: Locale,
) -> TaskStatusViewModel:
    status = _ui_status(_string(raw_task.get("status"), field_name="status"))
    return TaskStatusViewModel(
        task_id=_string(raw_task.get("task_id"), field_name="task_id"),
        trace_id=_string(raw_task.get("trace_id"), field_name="trace_id"),
        kind=_string(raw_task.get("kind"), field_name="kind"),
        status=status,
        label=translate(_label_key(status), locale),
        result=_mapping_or_empty(raw_task.get("result"), field_name="result"),
        error_message=_optional_string(raw_task.get("error_message"), field_name="error_message"),
    )


def _ui_status(raw_status: str) -> UiTaskStatus:
    if raw_status == "queued":
        return UiTaskStatus.QUEUED
    if raw_status == "running":
        return UiTaskStatus.RUNNING
    if raw_status in {"partial", "degraded"}:
        return UiTaskStatus.PARTIAL
    if raw_status == "failed":
        return UiTaskStatus.FAILED
    if raw_status in {"succeeded", "completed"}:
        return UiTaskStatus.COMPLETED
    raise ValueError(f"Unsupported task status: {raw_status}")


def _label_key(status: UiTaskStatus) -> TranslationKey:
    if status is UiTaskStatus.QUEUED:
        return TranslationKey.TASK_STATUS_QUEUED
    if status is UiTaskStatus.RUNNING:
        return TranslationKey.TASK_STATUS_RUNNING
    if status is UiTaskStatus.PARTIAL:
        return TranslationKey.TASK_STATUS_PARTIAL
    if status is UiTaskStatus.FAILED:
        return TranslationKey.TASK_STATUS_FAILED
    return TranslationKey.TASK_STATUS_COMPLETED


def _mapping_or_empty(value: object, field_name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return cast(Mapping[str, Any], value)


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value
