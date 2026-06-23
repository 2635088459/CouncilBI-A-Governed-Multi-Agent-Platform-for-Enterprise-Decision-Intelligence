from typing import Any, Mapping

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext, HistoryListViewModel
from chatbi.frontend.history_state import HistoryItemStatus, HistoryPageStore


class FakeHistoryApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, int]] = []

    def load_history(
        self,
        context: FrontendUserContext,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> HistoryListViewModel:
        self.calls.append((cursor, page_size))
        if cursor is None:
            return HistoryListViewModel(
                items=(
                    _raw_item(
                        trace_id="trc_001",
                        question="Show revenue trend.",
                        status="succeeded",
                    ),
                ),
                next_cursor="cursor_2",
                page_size=page_size,
            )
        return HistoryListViewModel(
            items=(
                _raw_item(
                    trace_id="trc_002",
                    question="DROP TABLE orders",
                    status="failed",
                ),
            ),
            next_cursor=None,
            page_size=page_size,
        )


class ErrorHistoryApiClient(FakeHistoryApiClient):
    def load_history(
        self,
        context: FrontendUserContext,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> HistoryListViewModel:
        raise ValueError("History API failed.")


def test_load_first_page_replaces_items_and_sets_cursor() -> None:
    api_client = FakeHistoryApiClient()
    store = HistoryPageStore(
        context=_context(),
        api_client=api_client,
        page_size=1,
    )

    state = store.load_first_page()

    assert state.is_loading is False
    assert state.error_message is None
    assert state.has_more is True
    assert state.next_cursor == "cursor_2"
    assert state.items[0].trace_id == "trc_001"
    assert state.items[0].status is HistoryItemStatus.SUCCEEDED
    assert state.items[0].can_replay is True
    assert api_client.calls == [(None, 1)]


def test_load_next_page_appends_items_until_cursor_is_empty() -> None:
    store = HistoryPageStore(
        context=_context(),
        api_client=FakeHistoryApiClient(),
        page_size=1,
    )

    store.load_first_page()
    state = store.load_next_page()

    assert state.has_more is False
    assert [item.trace_id for item in state.items] == ["trc_001", "trc_002"]
    assert state.items[1].status is HistoryItemStatus.FAILED
    assert state.items[1].can_replay is False


def test_load_next_page_does_nothing_without_cursor() -> None:
    store = HistoryPageStore(
        context=_context(),
        api_client=FakeHistoryApiClient(),
        page_size=1,
    )

    store.load_first_page()
    store.load_next_page()
    state = store.load_next_page()

    assert [item.trace_id for item in state.items] == ["trc_001", "trc_002"]


def test_select_for_replay_returns_trace_and_question() -> None:
    store = HistoryPageStore(context=_context(), api_client=FakeHistoryApiClient())
    store.load_first_page()

    state = store.select_for_replay("trc_001")

    assert state.error_message is None
    assert state.selected_replay is not None
    assert state.selected_replay.trace_id == "trc_001"
    assert state.selected_replay.question == "Show revenue trend."


def test_select_for_replay_rejects_failed_history_item() -> None:
    store = HistoryPageStore(context=_context(), api_client=FakeHistoryApiClient())
    store.load_first_page()
    store.load_next_page()

    state = store.select_for_replay("trc_002")

    assert state.selected_replay is None
    assert state.error_message == "Only successful queries can be replayed."


def test_load_first_page_records_error_without_dropping_existing_items() -> None:
    store = HistoryPageStore(context=_context(), api_client=ErrorHistoryApiClient())

    state = store.load_first_page()

    assert state.is_loading is False
    assert state.items == ()
    assert state.error_message == "History API failed."


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )


def _raw_item(
    trace_id: str,
    question: str,
    status: str,
) -> Mapping[str, Any]:
    return {
        "trace_id": trace_id,
        "session_id": "s_001",
        "question": question,
        "status": status,
        "created_at": "2026-06-18T12:00:00Z",
    }
