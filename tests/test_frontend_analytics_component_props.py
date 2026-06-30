from typing import Any, Mapping

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.analytics_state import AnalyticsPageState
from chatbi.frontend.api_client import (
    FrontendAnalyticsRequest,
    FrontendAnalyticsResultViewModel,
    FrontendUserContext,
)
from chatbi.frontend.component_props import ComponentId, build_analytics_page_props
from chatbi.frontend.task_status_state import TaskStatusViewModel, UiTaskStatus


def test_build_analytics_page_props_returns_empty_state() -> None:
    state = AnalyticsPageState(context=_context())

    props = build_analytics_page_props(state, Locale.EN)

    assert props.title == "Analytics"
    assert props.empty_state == "Run metric analytics to inspect anomalies and forecasts."
    assert props.input.trace_id == ""
    assert props.input.can_run is False
    assert props.input.can_enqueue is False
    assert props.result is None
    assert props.task is None
    assert props.tab_order == (
        ComponentId.ANALYTICS_RUN,
        ComponentId.ANALYTICS_ENQUEUE,
        ComponentId.ANALYTICS_LOAD_RESULT,
    )


def test_build_analytics_page_props_renders_result_summary() -> None:
    state = AnalyticsPageState(
        context=_context(),
        request=_request("tr_analytics_props"),
        latest_result=_result("tr_analytics_props"),
    )

    props = build_analytics_page_props(state, Locale.EN)

    assert props.input.trace_id == "tr_analytics_props"
    assert props.input.metric_id == "revenue"
    assert props.input.grain == "day"
    assert props.input.row_count == 3
    assert props.input.can_run is True
    assert props.result is not None
    assert props.result.method_label == "Method: rolling_zscore_linear_forecast"
    assert props.result.model_version_label == "Model version: analytics-v2-rule-based-001"
    assert props.result.forecast_points_label == "Forecast points: 1"
    assert props.result.warning_count_label == "0 quality warnings"
    assert props.tab_order[-1] is ComponentId.ANALYTICS_RESULT


def test_build_analytics_page_props_renders_async_task_card() -> None:
    state = AnalyticsPageState(
        context=_context(),
        request=_request("tr_analytics_task_props"),
        latest_task=TaskStatusViewModel(
            task_id="task_analytics_001",
            trace_id="tr_analytics_task_props",
            kind="analytics",
            status=UiTaskStatus.QUEUED,
            label="Queued",
            result={},
            error_message=None,
        ),
    )

    props = build_analytics_page_props(state, Locale.EN)

    assert props.task is not None
    assert props.task.task_id == "task_analytics_001"
    assert props.task.tone == "neutral"
    assert props.task.result_count_label == "0 result fields"
    assert props.tab_order[-1] is ComponentId.ANALYTICS_TASK


def test_build_analytics_page_props_localizes_zh_cn() -> None:
    state = AnalyticsPageState(
        context=_context(locale=Locale.ZH_CN),
        request=_request("tr_analytics_zh"),
        latest_result=_result("tr_analytics_zh"),
    )

    props = build_analytics_page_props(state, Locale.ZH_CN)

    assert props.title == "分析"
    assert props.input.run_label == "运行分析"
    assert props.input.enqueue_label == "加入分析队列"
    assert props.result is not None
    assert props.result.method_label == "方法：rolling_zscore_linear_forecast"
    assert props.result.forecast_points_label == "预测点数：1"


def _context(locale: Locale = Locale.EN) -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=locale,
        role=UserRole.ANALYST,
        bearer_token="test-token",
    )


def _request(trace_id: str) -> FrontendAnalyticsRequest:
    return FrontendAnalyticsRequest(
        trace_id=trace_id,
        metric_id="revenue",
        semantic_version_id="sem_v2",
        time_column="date",
        value_column="revenue",
        grain="day",
        rows=(
            {"date": "2026-06-01", "revenue": 100.0},
            {"date": "2026-06-02", "revenue": 105.0},
            {"date": "2026-06-03", "revenue": 110.0},
        ),
    )


def _result(trace_id: str) -> FrontendAnalyticsResultViewModel:
    forecast: Mapping[str, Any] = {
        "timestamp": "2026-06-04",
        "value": 115.0,
        "lower": 105.0,
        "upper": 125.0,
    }
    return FrontendAnalyticsResultViewModel(
        trace_id=trace_id,
        metric_id="revenue",
        semantic_version_id="sem_v2",
        method="rolling_zscore_linear_forecast",
        model_version="analytics-v2-rule-based-001",
        anomaly_points=(),
        forecast_points=(forecast,),
        quality_warnings=(),
        explanation="Deterministic analytics result.",
    )
