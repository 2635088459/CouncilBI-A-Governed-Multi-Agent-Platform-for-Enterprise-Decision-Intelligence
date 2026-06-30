from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.app_shell import AppShellState, FrontendRoute
from chatbi.frontend.app_shell_props import build_app_shell_props
from chatbi.frontend.catalog_state import CatalogPageState
from chatbi.frontend.chat_state import ChatPageState
from chatbi.frontend.component_props import ComponentId
from chatbi.frontend.evaluation_state import EvaluationPageState
from chatbi.frontend.history_state import HistoryPageState
from chatbi.frontend.task_status_page_state import TaskStatusPageState


def test_build_app_shell_props_marks_current_route_active() -> None:
    props = build_app_shell_props(
        _state(route=FrontendRoute.CATALOG),
        Locale.EN,
    )

    assert props.title == "InsightOps AI"
    assert props.active_route is FrontendRoute.CATALOG
    assert [item.route for item in props.nav_items] == [
        FrontendRoute.CHAT,
        FrontendRoute.HISTORY,
        FrontendRoute.CATALOG,
        FrontendRoute.TASK_STATUS,
        FrontendRoute.EVALUATION,
    ]
    assert [item.label for item in props.nav_items] == [
        "InsightOps AI",
        "Query History",
        "Metric Catalog",
        "Task Status",
        "Evaluation",
    ]
    assert [item.is_active for item in props.nav_items] == [
        False,
        False,
        True,
        False,
        False,
    ]
    assert props.tab_order == (
        ComponentId.NAV_CHAT,
        ComponentId.NAV_HISTORY,
        ComponentId.NAV_CATALOG,
        ComponentId.NAV_TASK_STATUS,
        ComponentId.NAV_EVALUATION,
    )


def test_build_app_shell_props_localizes_navigation_labels() -> None:
    props = build_app_shell_props(
        _state(route=FrontendRoute.HISTORY, locale=Locale.ZH_CN),
        Locale.ZH_CN,
    )

    assert [item.label for item in props.nav_items] == [
        "InsightOps AI",
        "查询历史",
        "指标目录",
        "任务状态",
        "评估",
    ]
    assert props.nav_items[1].is_active is True


def _state(
    route: FrontendRoute,
    locale: Locale = Locale.EN,
) -> AppShellState:
    context = _context(locale)
    return AppShellState(
        route=route,
        chat=ChatPageState(context=context),
        history=HistoryPageState(context=context),
        catalog=CatalogPageState(context=context),
        task_status=TaskStatusPageState(context=context),
        evaluation=EvaluationPageState(context=context),
    )


def _context(locale: Locale) -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=locale,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )
