from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.task_status_page_state import TaskStatusPageStore
from chatbi.frontend.task_status_state import TaskStatusViewModel, UiTaskStatus


class FakeTaskStatusApiClient:
    def __init__(self) -> None:
        self.loaded_task_ids: list[str] = []

    def load_task_status(
        self,
        context: FrontendUserContext,
        task_id: str,
    ) -> TaskStatusViewModel:
        self.loaded_task_ids.append(task_id)
        return TaskStatusViewModel(
            task_id=task_id,
            trace_id="trc_task",
            kind="indexing",
            status=UiTaskStatus.COMPLETED,
            label="Completed",
            result={"document_id": "doc_001", "chunk_count": 2},
            error_message=None,
        )


class ErrorTaskStatusApiClient(FakeTaskStatusApiClient):
    def load_task_status(
        self,
        context: FrontendUserContext,
        task_id: str,
    ) -> TaskStatusViewModel:
        raise ValueError("Task id was not found.")


def test_load_task_status_stores_latest_status() -> None:
    api_client = FakeTaskStatusApiClient()
    store = TaskStatusPageStore(context=_context(), api_client=api_client)

    state = store.load_task(" task_001 ")

    assert state.task_id == "task_001"
    assert state.is_loading is False
    assert state.error_message is None
    assert state.current_status is not None
    assert state.current_status.status is UiTaskStatus.COMPLETED
    assert state.has_task is True
    assert api_client.loaded_task_ids == ["task_001"]


def test_refresh_current_task_reuses_selected_task_id() -> None:
    api_client = FakeTaskStatusApiClient()
    store = TaskStatusPageStore(context=_context(), api_client=api_client)

    store.set_task_id("task_001")
    state = store.load_current_task()

    assert state.current_status is not None
    assert state.current_status.task_id == "task_001"
    assert api_client.loaded_task_ids == ["task_001"]


def test_load_current_task_reports_missing_task_id() -> None:
    store = TaskStatusPageStore(context=_context(), api_client=FakeTaskStatusApiClient())

    state = store.load_current_task()

    assert state.current_status is None
    assert state.error_message == "Task id is required."


def test_load_task_status_records_error_without_dropping_previous_status() -> None:
    working_store = TaskStatusPageStore(
        context=_context(),
        api_client=FakeTaskStatusApiClient(),
    )
    previous_state = working_store.load_task("task_001")
    error_store = TaskStatusPageStore(
        context=_context(),
        api_client=ErrorTaskStatusApiClient(),
    )

    state = error_store.load_task("task_missing")

    assert previous_state.current_status is not None
    assert state.current_status is None
    assert state.is_loading is False
    assert state.error_message == "Task id was not found."


def test_set_task_id_rejects_empty_input() -> None:
    store = TaskStatusPageStore(context=_context(), api_client=FakeTaskStatusApiClient())

    try:
        store.set_task_id("  ")
    except ValueError as exc:
        assert str(exc) == "Task id is required."
    else:
        raise AssertionError("Expected empty task id to fail.")


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )
