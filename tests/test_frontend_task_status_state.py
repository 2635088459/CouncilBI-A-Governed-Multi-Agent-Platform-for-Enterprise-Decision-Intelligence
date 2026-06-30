import pytest

from chatbi.core.contracts import Locale
from chatbi.frontend.task_status_state import (
    UiTaskStatus,
    build_task_status_view_model,
)


def test_task_status_maps_backend_succeeded_to_completed() -> None:
    status = build_task_status_view_model(
        {
            "task_id": "task_001",
            "trace_id": "trc_task",
            "kind": "indexing",
            "status": "succeeded",
            "result": {"document_id": "doc_001", "chunk_count": 2},
            "error_message": None,
        },
        Locale.EN,
    )

    assert status.status is UiTaskStatus.COMPLETED
    assert status.label == "Completed"
    assert status.is_terminal is True
    assert status.result["chunk_count"] == 2


def test_task_status_renders_all_required_states() -> None:
    cases = {
        "queued": (UiTaskStatus.QUEUED, "Queued", False),
        "running": (UiTaskStatus.RUNNING, "Running", False),
        "partial": (UiTaskStatus.PARTIAL, "Partially completed", True),
        "failed": (UiTaskStatus.FAILED, "Failed", True),
        "completed": (UiTaskStatus.COMPLETED, "Completed", True),
    }

    for raw_status, (expected_status, expected_label, expected_terminal) in cases.items():
        status = build_task_status_view_model(
            {
                "task_id": f"task_{raw_status}",
                "trace_id": "trc_task",
                "kind": "analytics",
                "status": raw_status,
                "result": {},
                "error_message": "failed" if raw_status == "failed" else None,
            },
            Locale.EN,
        )

        assert status.status is expected_status
        assert status.label == expected_label
        assert status.is_terminal is expected_terminal


def test_task_status_localizes_partial_state() -> None:
    status = build_task_status_view_model(
        {
            "task_id": "task_partial",
            "trace_id": "trc_task",
            "kind": "analytics",
            "status": "degraded",
            "result": {"available_rows": 10},
            "error_message": None,
        },
        Locale.ZH_CN,
    )

    assert status.status is UiTaskStatus.PARTIAL
    assert status.label == "部分完成"
    assert status.is_warning is True


def test_task_status_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="Unsupported task status"):
        build_task_status_view_model(
            {
                "task_id": "task_unknown",
                "trace_id": "trc_task",
                "kind": "analytics",
                "status": "paused",
            },
            Locale.EN,
        )
