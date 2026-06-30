import pytest

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import (
    FrontendAnalyticsResultViewModel,
    FrontendApiClient,
    FrontendUserContext,
)
from chatbi.frontend.api_fixtures import (
    partial_failure_chat_query_fixture,
    sql_guardrail_denied_fixture,
)
from chatbi.frontend.app_shell import AppShellState, FrontendAppShell, FrontendRoute
from chatbi.frontend.analytics_state import AnalyticsPageState
from chatbi.frontend.app_screen_model import build_app_screen_model
from chatbi.frontend.catalog_state import CatalogPageState
from chatbi.frontend.chat_state import ChatPageState
from chatbi.frontend.evaluation_state import EvaluationPageState
from chatbi.frontend.fixture_transport import FixtureJsonTransport
from chatbi.frontend.history_state import HistoryPageState
from chatbi.frontend.render_model import (
    RenderRegion,
    build_app_render_model,
    build_chat_screen_render_model,
)
from chatbi.frontend.ui_answer_state import UiAnswerStatus
from chatbi.frontend.task_status_page_state import TaskStatusPageState


def test_successful_fixture_render_model_contains_answer_regions() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FrontendApiClient(FixtureJsonTransport()),
    )

    shell.submit_chat_question("show monthly revenue")
    model = build_chat_screen_render_model(shell.chat_props())

    assert model.visible_regions() == (
        RenderRegion.CHAT_INPUT,
        RenderRegion.SEND_BUTTON,
        RenderRegion.ANSWER_TEXT,
        RenderRegion.TABLE,
        RenderRegion.CHART,
        RenderRegion.EVIDENCE_LIST,
        RenderRegion.WARNING_LIST,
        RenderRegion.TRACE_ID,
    )
    assert _element_text(model, RenderRegion.ANSWER_TEXT) == "Revenue trend is ready."
    assert _element_payload(model, RenderRegion.TABLE)["columns"] == [
        "order_month",
        "revenue",
    ]
    assert _element_payload(model, RenderRegion.CHART)["chart_type"] == "line"
    assert _element_payload(model, RenderRegion.EVIDENCE_LIST)["items"][0]["source_id"] == "doc_001"
    assert _element_payload(model, RenderRegion.WARNING_LIST)["items"] == []
    assert _element_payload(model, RenderRegion.TRACE_ID)["copy_value"] == "trc_fixture_success"


def test_app_render_model_includes_shell_navigation_and_active_page() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FrontendApiClient(FixtureJsonTransport()),
    )

    shell.load_catalog()
    model = build_app_render_model(shell.screen_model())

    assert model.visible_regions() == (
        RenderRegion.APP_SHELL,
        RenderRegion.NAVIGATION,
        RenderRegion.ACTIVE_PAGE,
        RenderRegion.CATALOG_SEARCH,
        RenderRegion.CATALOG_LIST,
        RenderRegion.CATALOG_DETAIL,
    )
    assert _element_text(model, RenderRegion.APP_SHELL) == "InsightOps AI"
    assert _element_payload(model, RenderRegion.APP_SHELL)["active_route"] == "catalog"
    nav_items = _element_payload(model, RenderRegion.NAVIGATION)["items"]
    assert nav_items[2]["route"] == "catalog"
    assert nav_items[2]["is_active"] is True
    assert _element_payload(model, RenderRegion.ACTIVE_PAGE)["route"] == "catalog"
    assert _element_text(model, RenderRegion.CATALOG_SEARCH) == "Search metrics..."
    assert _element_payload(model, RenderRegion.CATALOG_LIST)["metrics"] == ["revenue"]
    assert _element_text(model, RenderRegion.CATALOG_DETAIL) == "revenue"


def test_app_render_model_includes_history_task_and_evaluation_regions() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FrontendApiClient(FixtureJsonTransport()),
    )

    shell.load_history()
    history_model = build_app_render_model(shell.screen_model())
    shell.load_task_status("task_fixture")
    task_model = build_app_render_model(shell.screen_model())
    shell.run_evaluation(eval_suite_id="frontend_smoke", questions=("Show revenue trend.",))
    evaluation_model = build_app_render_model(shell.screen_model())

    assert RenderRegion.HISTORY_LIST in history_model.visible_regions()
    assert _element_payload(history_model, RenderRegion.HISTORY_LIST)["items"][0]["trace_id"] == (
        "trc_fixture_success"
    )
    assert RenderRegion.TASK_STATUS_CARD in task_model.visible_regions()
    assert _element_payload(task_model, RenderRegion.TASK_STATUS_CARD)["status"] == "completed"
    assert RenderRegion.EVALUATION_REPORT in evaluation_model.visible_regions()
    assert _element_payload(evaluation_model, RenderRegion.EVALUATION_REPORT)["tone"] == "success"


def test_app_render_model_includes_analytics_result_region() -> None:
    context = _context()
    screen = build_app_screen_model(
        AppShellState(
            route=FrontendRoute.ANALYTICS,
            chat=ChatPageState(context=context),
            history=HistoryPageState(context=context),
            catalog=CatalogPageState(context=context),
            analytics=AnalyticsPageState(
                context=context,
                latest_result=FrontendAnalyticsResultViewModel(
                    trace_id="tr_analytics_render",
                    metric_id="revenue",
                    semantic_version_id="sem_v2",
                    method="rolling_zscore_linear_forecast",
                    model_version="analytics-v2-rule-based-001",
                    anomaly_points=(),
                    forecast_points=(
                        {
                            "timestamp": "2026-06-04",
                            "value": 115.0,
                            "lower": 105.0,
                            "upper": 125.0,
                        },
                    ),
                    quality_warnings=(),
                    explanation="Deterministic analytics result.",
                ),
            ),
            task_status=TaskStatusPageState(context=context),
            evaluation=EvaluationPageState(context=context),
        ),
        Locale.EN,
    )
    model = build_app_render_model(screen)

    assert RenderRegion.ANALYTICS_RESULT in model.visible_regions()
    assert _element_payload(model, RenderRegion.ANALYTICS_RESULT)["metric_id"] == "revenue"
    assert _element_payload(model, RenderRegion.ANALYTICS_RESULT)["forecast_points_label"] == (
        "Forecast points: 1"
    )


def test_app_render_model_includes_chat_regions_for_chat_route() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FrontendApiClient(FixtureJsonTransport()),
    )

    shell.submit_chat_question("show monthly revenue")
    model = build_app_render_model(shell.screen_model())

    assert model.visible_regions() == (
        RenderRegion.APP_SHELL,
        RenderRegion.NAVIGATION,
        RenderRegion.ACTIVE_PAGE,
        RenderRegion.CHAT_INPUT,
        RenderRegion.SEND_BUTTON,
        RenderRegion.ANSWER_TEXT,
        RenderRegion.TABLE,
        RenderRegion.CHART,
        RenderRegion.EVIDENCE_LIST,
        RenderRegion.WARNING_LIST,
        RenderRegion.TRACE_ID,
    )
    assert _element_text(model, RenderRegion.ANSWER_TEXT) == "Revenue trend is ready."


def test_partial_failure_fixture_render_model_keeps_data_visible_with_warning() -> None:
    transport = FixtureJsonTransport(fixtures=(partial_failure_chat_query_fixture(),))
    shell = FrontendAppShell(
        context=_context(),
        api_client=FrontendApiClient(transport),
    )

    shell.submit_chat_question("show monthly revenue")
    props = shell.chat_props()
    model = build_chat_screen_render_model(props)

    assert props.answer_state.status is UiAnswerStatus.PARTIAL
    assert RenderRegion.TABLE in model.visible_regions()
    assert RenderRegion.CHART in model.visible_regions()
    assert _element_payload(model, RenderRegion.WARNING_LIST)["items"][0]["code"] == (
        "AGENT_PARTIAL_FAILURE"
    )


def test_sql_denial_render_model_shows_error_boundary_and_trace() -> None:
    transport = FixtureJsonTransport(fixtures=(sql_guardrail_denied_fixture(),))
    shell = FrontendAppShell(
        context=_context(),
        api_client=FrontendApiClient(transport),
    )

    shell.submit_chat_question("drop table orders")
    model = build_chat_screen_render_model(shell.chat_props())

    assert RenderRegion.ERROR_BOUNDARY in model.visible_regions()
    assert RenderRegion.ANSWER_TEXT not in model.visible_regions()
    assert _element_payload(model, RenderRegion.ERROR_BOUNDARY)["code"] == (
        "SQL_GUARDRAIL_DENIED"
    )
    assert _element_payload(model, RenderRegion.TRACE_ID)["copy_value"] == "trc_fixture_denied"


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )


def _element_text(model: object, region: RenderRegion) -> str | None:
    element = _element(model, region)
    return element.text


def _element_payload(model: object, region: RenderRegion) -> object:
    element = _element(model, region)
    assert element.payload is not None
    return element.payload


def _element(model: object, region: RenderRegion) -> object:
    elements = getattr(model, "elements")
    for element in elements:
        if element.region is region:
            return element
    raise AssertionError(f"Missing render region: {region.value}")
