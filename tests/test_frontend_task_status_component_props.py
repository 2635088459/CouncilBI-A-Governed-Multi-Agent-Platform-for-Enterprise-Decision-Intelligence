from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.component_props import (
    ComponentId,
    build_task_status_page_props,
)
from chatbi.frontend.task_status_page_state import TaskStatusPageState
from chatbi.frontend.task_status_state import TaskStatusViewModel, UiTaskStatus


def test_build_task_status_page_props_returns_empty_state() -> None:
    state = TaskStatusPageState(context=_context())

    props = build_task_status_page_props(state, Locale.EN)

    assert props.title == "Task Status"
    assert props.empty_state == "Enter a task id to check long-running work."
    assert props.input.value == ""
    assert props.input.placeholder == "Enter a task id..."
    assert props.input.load_label == "Load status"
    assert props.input.refresh_label == "Refresh"
    assert props.input.can_load is False
    assert props.input.can_refresh is False
    assert props.status_card is None
    assert props.tab_order == (
        ComponentId.TASK_STATUS_INPUT,
        ComponentId.TASK_STATUS_LOAD,
    )


def test_build_task_status_page_props_renders_completed_status_card() -> None:
    state = TaskStatusPageState(
        context=_context(),
        task_id="task_001",
        current_status=TaskStatusViewModel(
            task_id="task_001",
            trace_id="trc_task",
            kind="indexing",
            status=UiTaskStatus.COMPLETED,
            label="Completed",
            result={"document_id": "doc_001", "chunk_count": 2},
            error_message=None,
        ),
    )

    props = build_task_status_page_props(state, Locale.EN)

    assert props.input.value == "task_001"
    assert props.input.can_load is True
    assert props.input.can_refresh is True
    assert props.status_card is not None
    assert props.status_card.task_id == "task_001"
    assert props.status_card.trace_id == "trc_task"
    assert props.status_card.status is UiTaskStatus.COMPLETED
    assert props.status_card.tone == "success"
    assert props.status_card.is_terminal is True
    assert props.status_card.result_count_label == "2 result fields"
    assert props.tab_order == (
        ComponentId.TASK_STATUS_INPUT,
        ComponentId.TASK_STATUS_LOAD,
        ComponentId.TASK_STATUS_REFRESH,
        ComponentId.TASK_STATUS_CARD,
    )


def test_build_task_status_page_props_renders_failed_status_card() -> None:
    state = TaskStatusPageState(
        context=_context(),
        task_id="task_failed",
        current_status=TaskStatusViewModel(
            task_id="task_failed",
            trace_id="trc_task",
            kind="indexing",
            status=UiTaskStatus.FAILED,
            label="Failed",
            result={},
            error_message="embedding service unavailable",
        ),
    )

    props = build_task_status_page_props(state, Locale.EN)

    assert props.status_card is not None
    assert props.status_card.tone == "danger"
    assert props.status_card.error_message == "embedding service unavailable"


def test_build_task_status_page_props_localizes_zh_cn() -> None:
    state = TaskStatusPageState(
        context=_context(locale=Locale.ZH_CN),
        task_id="task_partial",
        current_status=TaskStatusViewModel(
            task_id="task_partial",
            trace_id="trc_task",
            kind="analytics",
            status=UiTaskStatus.PARTIAL,
            label="部分完成",
            result={"available_rows": 10},
            error_message=None,
        ),
    )

    props = build_task_status_page_props(state, Locale.ZH_CN)

    assert props.title == "任务状态"
    assert props.input.placeholder == "请输入任务 ID..."
    assert props.input.load_label == "加载状态"
    assert props.status_card is not None
    assert props.status_card.tone == "warning"
    assert props.status_card.result_count_label == "1 个结果字段"


def _context(locale: Locale = Locale.EN) -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=locale,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )
