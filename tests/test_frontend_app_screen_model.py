from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendApiClient, FrontendUserContext
from chatbi.frontend.app_screen_model import build_app_screen_model
from chatbi.frontend.app_shell import AppShellState, FrontendAppShell, FrontendRoute
from chatbi.frontend.catalog_state import CatalogPageState
from chatbi.frontend.chat_state import ChatPageState
from chatbi.frontend.component_props import (
    CatalogPageProps,
    ChatPageProps,
    EvaluationPageProps,
    HistoryPageProps,
    TaskStatusPageProps,
)
from chatbi.frontend.evaluation_state import EvaluationPageState
from chatbi.frontend.fixture_transport import FixtureJsonTransport
from chatbi.frontend.history_state import HistoryPageState
from chatbi.frontend.task_status_page_state import TaskStatusPageState


def test_build_app_screen_model_selects_active_page_props_for_each_route() -> None:
    expected_types = {
        FrontendRoute.CHAT: ChatPageProps,
        FrontendRoute.HISTORY: HistoryPageProps,
        FrontendRoute.CATALOG: CatalogPageProps,
        FrontendRoute.TASK_STATUS: TaskStatusPageProps,
        FrontendRoute.EVALUATION: EvaluationPageProps,
    }

    for route, expected_type in expected_types.items():
        model = build_app_screen_model(_state(route), Locale.EN)

        assert model.active_route is route
        assert model.shell.active_route is route
        assert isinstance(model.active_page, expected_type)


def test_frontend_app_shell_screen_model_tracks_navigation() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FrontendApiClient(FixtureJsonTransport()),
    )

    initial_model = shell.screen_model()
    shell.load_catalog()
    catalog_model = shell.screen_model()

    assert initial_model.active_route is FrontendRoute.CHAT
    assert isinstance(initial_model.active_page, ChatPageProps)
    assert catalog_model.active_route is FrontendRoute.CATALOG
    assert isinstance(catalog_model.active_page, CatalogPageProps)
    assert catalog_model.shell.nav_items[2].is_active is True


def _state(route: FrontendRoute) -> AppShellState:
    context = _context()
    return AppShellState(
        route=route,
        chat=ChatPageState(context=context),
        history=HistoryPageState(context=context),
        catalog=CatalogPageState(context=context),
        task_status=TaskStatusPageState(context=context),
        evaluation=EvaluationPageState(context=context),
    )


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )
