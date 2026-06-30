from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.component_props import ComponentId, build_history_page_props
from chatbi.frontend.history_state import (
    HistoryItemStatus,
    HistoryItemViewModel,
    HistoryPageState,
    ReplaySelection,
)


def test_build_history_page_props_renders_empty_state() -> None:
    state = HistoryPageState(context=_context(locale=Locale.ZH_CN))

    props = build_history_page_props(state, Locale.ZH_CN)

    assert props.title == "查询历史"
    assert props.empty_state == "还没有查询历史。"
    assert props.items == ()
    assert props.can_load_more is False
    assert props.tab_order == (ComponentId.HISTORY_LIST,)


def test_build_history_page_props_renders_records_and_replay_actions() -> None:
    state = HistoryPageState(
        context=_context(),
        items=(
            _item(
                trace_id="trc_001",
                question="Show revenue trend.",
                status=HistoryItemStatus.SUCCEEDED,
            ),
            _item(
                trace_id="trc_002",
                question="DROP TABLE orders",
                status=HistoryItemStatus.FAILED,
            ),
        ),
        next_cursor="cursor_2",
        selected_replay=ReplaySelection(
            trace_id="trc_001",
            question="Show revenue trend.",
        ),
    )

    props = build_history_page_props(state, Locale.EN)

    assert props.title == "Query History"
    assert props.load_more_label == "Load more"
    assert props.can_load_more is True
    assert props.selected_trace_id == "trc_001"
    assert props.items[0].trace_id == "trc_001"
    assert props.items[0].status_label == "Succeeded"
    assert props.items[0].replay_label == "Replay"
    assert props.items[0].can_replay is True
    assert props.items[0].is_selected is True
    assert props.items[1].status_label == "Failed"
    assert props.items[1].can_replay is False
    assert props.tab_order == (
        ComponentId.HISTORY_LIST,
        ComponentId.HISTORY_REPLAY,
        ComponentId.HISTORY_LOAD_MORE,
    )


def test_build_history_page_props_disables_actions_while_loading() -> None:
    state = HistoryPageState(
        context=_context(),
        items=(
            _item(
                trace_id="trc_001",
                question="Show revenue trend.",
                status=HistoryItemStatus.SUCCEEDED,
            ),
        ),
        next_cursor="cursor_2",
        is_loading=True,
    )

    props = build_history_page_props(state, Locale.EN)

    assert props.is_loading is True
    assert props.can_load_more is False
    assert props.items[0].can_replay is False


def _context(locale: Locale = Locale.EN) -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=locale,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )


def _item(
    trace_id: str,
    question: str,
    status: HistoryItemStatus,
) -> HistoryItemViewModel:
    return HistoryItemViewModel(
        trace_id=trace_id,
        session_id="s_001",
        question=question,
        status=status,
        created_at="2026-06-18T12:00:00Z",
        can_replay=status is HistoryItemStatus.SUCCEEDED,
    )
