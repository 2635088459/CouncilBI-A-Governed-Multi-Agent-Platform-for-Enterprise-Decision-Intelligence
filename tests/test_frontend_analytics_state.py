from typing import Any, Mapping

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.analytics_state import AnalyticsPageStore
from chatbi.frontend.api_client import (
    FrontendAnalyticsRequest,
    FrontendAnalyticsResultViewModel,
    FrontendUserContext,
)
from chatbi.frontend.task_status_state import TaskStatusViewModel, UiTaskStatus


class FakeAnalyticsApiClient:
    def __init__(self) -> None:
        self.analyzed: list[str] = []
        self.enqueued: list[str] = []
        self.loaded_trace_ids: list[str] = []

    def analyze_metric(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> FrontendAnalyticsResultViewModel:
        self.analyzed.append(request.trace_id)
        return _result(request.trace_id, request.metric_id)

    def enqueue_analytics(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> TaskStatusViewModel:
        self.enqueued.append(request.trace_id)
        return TaskStatusViewModel(
            task_id="task_analytics_001",
            trace_id=request.trace_id,
            kind="analytics",
            status=UiTaskStatus.QUEUED,
            label="Queued",
            result={},
            error_message=None,
        )

    def load_analytics_result(
        self,
        context: FrontendUserContext,
        trace_id: str,
    ) -> FrontendAnalyticsResultViewModel:
        self.loaded_trace_ids.append(trace_id)
        return _result(trace_id, "revenue")


class ErrorAnalyticsApiClient(FakeAnalyticsApiClient):
    def analyze_metric(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> FrontendAnalyticsResultViewModel:
        raise ValueError("Analytics API failed.")


def test_run_request_stores_latest_result() -> None:
    api_client = FakeAnalyticsApiClient()
    store = AnalyticsPageStore(context=_context(), api_client=api_client)

    state = store.run_request(_request("tr_frontend_analytics"))

    assert state.is_loading is False
    assert state.error_message is None
    assert state.latest_result is not None
    assert state.latest_result.trace_id == "tr_frontend_analytics"
    assert state.latest_task is None
    assert state.has_result is True
    assert api_client.analyzed == ["tr_frontend_analytics"]


def test_run_current_request_requires_selected_request() -> None:
    store = AnalyticsPageStore(context=_context(), api_client=FakeAnalyticsApiClient())

    state = store.run_current_request()

    assert state.latest_result is None
    assert state.error_message == "Analytics request is required."


def test_set_request_then_run_current_request() -> None:
    api_client = FakeAnalyticsApiClient()
    store = AnalyticsPageStore(context=_context(), api_client=api_client)

    store.set_request(_request("tr_selected"))
    state = store.run_current_request()

    assert state.request is not None
    assert state.request.trace_id == "tr_selected"
    assert state.latest_result is not None
    assert api_client.analyzed == ["tr_selected"]


def test_enqueue_request_stores_latest_task() -> None:
    api_client = FakeAnalyticsApiClient()
    store = AnalyticsPageStore(context=_context(), api_client=api_client)

    state = store.enqueue_request(_request("tr_async"))

    assert state.latest_task is not None
    assert state.latest_task.task_id == "task_analytics_001"
    assert state.latest_task.status is UiTaskStatus.QUEUED
    assert state.has_task is True
    assert api_client.enqueued == ["tr_async"]


def test_load_result_by_trace_id_stores_latest_result() -> None:
    api_client = FakeAnalyticsApiClient()
    store = AnalyticsPageStore(context=_context(), api_client=api_client)

    state = store.load_result(" tr_lookup ")

    assert state.latest_result is not None
    assert state.latest_result.trace_id == "tr_lookup"
    assert api_client.loaded_trace_ids == ["tr_lookup"]


def test_run_request_records_error_without_result() -> None:
    store = AnalyticsPageStore(context=_context(), api_client=ErrorAnalyticsApiClient())

    state = store.run_request(_request("tr_error"))

    assert state.is_loading is False
    assert state.latest_result is None
    assert state.error_message == "Analytics API failed."


def test_request_validation_rejects_invalid_grain_and_empty_rows() -> None:
    store = AnalyticsPageStore(context=_context(), api_client=FakeAnalyticsApiClient())

    try:
        store.set_request(
            FrontendAnalyticsRequest(
                trace_id="tr_bad",
                metric_id="revenue",
                semantic_version_id="sem_v2",
                time_column="date",
                value_column="revenue",
                grain="hour",
                rows=({"date": "2026-06-01", "revenue": 100.0},),
            )
        )
    except ValueError as exc:
        assert str(exc) == "Analytics grain must be day, week, or month."
    else:
        raise AssertionError("Expected invalid grain to raise.")

    try:
        store.set_request(
            FrontendAnalyticsRequest(
                trace_id="tr_bad",
                metric_id="revenue",
                semantic_version_id="sem_v2",
                time_column="date",
                value_column="revenue",
                grain="day",
                rows=(),
            )
        )
    except ValueError as exc:
        assert str(exc) == "Analytics rows are required."
    else:
        raise AssertionError("Expected empty rows to raise.")


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
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


def _result(trace_id: str, metric_id: str) -> FrontendAnalyticsResultViewModel:
    forecast: Mapping[str, Any] = {
        "timestamp": "2026-06-04",
        "value": 115.0,
        "lower": 105.0,
        "upper": 125.0,
    }
    return FrontendAnalyticsResultViewModel(
        trace_id=trace_id,
        metric_id=metric_id,
        semantic_version_id="sem_v2",
        method="rolling_zscore_linear_forecast",
        model_version="analytics-v2-rule-based-001",
        anomaly_points=(),
        forecast_points=(forecast,),
        quality_warnings=(),
        explanation="Deterministic analytics result.",
    )
