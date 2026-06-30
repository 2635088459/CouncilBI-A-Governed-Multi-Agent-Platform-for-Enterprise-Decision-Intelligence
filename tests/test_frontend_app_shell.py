from chatbi.core.contracts import ChartType, Locale, UserRole
from chatbi.frontend.api_client import (
    EvaluationRunViewModel,
    FrontendAnalyticsRequest,
    FrontendAnalyticsResultViewModel,
    FrontendUserContext,
    HistoryListViewModel,
    MetricCatalogViewModel,
)
from chatbi.frontend.app_shell import FrontendAppShell, FrontendRoute
from chatbi.frontend.chat_state import ChatTurnStatus
from chatbi.frontend.evaluation_state import ReleaseGateStatus
from chatbi.frontend.task_status_state import TaskStatusViewModel, UiTaskStatus
from chatbi.frontend.view_models import (
    ChartCardViewModel,
    MessageBubbleViewModel,
    MessageRole,
    QueryResultViewModel,
    SqlExplainCardViewModel,
    TableCardViewModel,
)


class FakeFrontendAppApiClient:
    def __init__(self) -> None:
        self.submitted_questions: list[str] = []
        self.replayed_trace_ids: list[str] = []
        self.loaded_task_ids: list[str] = []
        self.analyzed_trace_ids: list[str] = []
        self.enqueued_trace_ids: list[str] = []
        self.loaded_analytics_trace_ids: list[str] = []

    def submit_question(
        self,
        context: FrontendUserContext,
        question: str,
        idempotency_key: str | None = None,
    ) -> QueryResultViewModel:
        self.submitted_questions.append(question)
        return _result(trace_id="trc_submit")

    def replay_query(
        self,
        context: FrontendUserContext,
        trace_id: str,
    ) -> QueryResultViewModel:
        self.replayed_trace_ids.append(trace_id)
        return _result(trace_id=trace_id)

    def load_history(
        self,
        context: FrontendUserContext,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> HistoryListViewModel:
        return HistoryListViewModel(
            items=(
                {
                    "trace_id": "trc_history",
                    "session_id": context.session_id,
                    "question": "Show revenue trend.",
                    "status": "succeeded",
                    "created_at": "2026-06-18T12:00:00Z",
                },
            ),
            next_cursor=None,
            page_size=page_size,
        )

    def load_metric_catalog(self, context: FrontendUserContext) -> MetricCatalogViewModel:
        return MetricCatalogViewModel(
            metrics=(
                {
                    "name": "revenue",
                    "sql_definition": "SUM(order_amount)",
                    "source_tables": ("orders",),
                    "semantic_version": "sem_v1",
                },
            )
        )

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

    def run_evaluation(
        self,
        context: FrontendUserContext,
        eval_suite_id: str,
        questions: tuple[str, ...] = (),
    ) -> EvaluationRunViewModel:
        return EvaluationRunViewModel(
            eval_run_id="eval_001",
            eval_suite_id=eval_suite_id,
            total_cases=len(questions) or 1,
            passed_cases=len(questions) or 1,
            failed_cases=0,
            overall_score=1.0,
            average_confidence=0.9,
            metric_breakdown={"sql_safety": 1.0},
            failed_cases_detail=(),
            release_gate_passed=True,
        )

    def analyze_metric(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> FrontendAnalyticsResultViewModel:
        self.analyzed_trace_ids.append(request.trace_id)
        return _analytics_result(request.trace_id)

    def enqueue_analytics(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> TaskStatusViewModel:
        self.enqueued_trace_ids.append(request.trace_id)
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
        self.loaded_analytics_trace_ids.append(trace_id)
        return _analytics_result(trace_id)


def test_app_shell_submits_chat_question_and_builds_chat_props() -> None:
    api_client = FakeFrontendAppApiClient()
    shell = FrontendAppShell(context=_context(), api_client=api_client)

    state = shell.submit_chat_question("Show revenue trend.")
    props = shell.chat_props()
    shell_props = shell.shell_props()

    assert state.route is FrontendRoute.CHAT
    assert shell_props.active_route is FrontendRoute.CHAT
    assert shell_props.nav_items[0].is_active is True
    assert state.chat.turns[0].status is ChatTurnStatus.ANSWERED
    assert api_client.submitted_questions == ["Show revenue trend."]
    assert props.turns[0].result is not None
    assert props.turns[0].result.answer_text == "Revenue trend is ready."


def test_app_shell_loads_history_selects_and_replays_into_chat() -> None:
    api_client = FakeFrontendAppApiClient()
    shell = FrontendAppShell(context=_context(), api_client=api_client)

    history_state = shell.load_history()
    history_props = shell.history_props()
    selected_state = shell.select_history_for_replay("trc_history")
    replay_state = shell.replay_selected_history()

    assert history_state.route is FrontendRoute.HISTORY
    assert history_props.items[0].trace_id == "trc_history"
    assert history_props.items[0].can_replay is True
    assert history_props.items[0].replay_label == "Replay"
    assert selected_state.history.selected_replay is not None
    assert replay_state.route is FrontendRoute.CHAT
    assert replay_state.history.selected_replay is None
    assert replay_state.chat.turns[0].status is ChatTurnStatus.REPLAYED
    assert replay_state.chat.turns[0].result is not None
    assert replay_state.chat.turns[0].result.trace_id == "trc_history"
    assert api_client.replayed_trace_ids == ["trc_history"]


def test_app_shell_loads_and_searches_catalog() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FakeFrontendAppApiClient(),
    )

    loaded_state = shell.load_catalog()
    searched_state = shell.search_catalog("revenue")
    props = shell.catalog_props()

    assert loaded_state.route is FrontendRoute.CATALOG
    assert loaded_state.catalog.selected_metric is not None
    assert loaded_state.catalog.selected_metric.name == "revenue"
    assert [metric.name for metric in searched_state.catalog.filtered_metrics] == ["revenue"]
    assert props.metrics[0].name == "revenue"
    assert props.selected_metric is not None
    assert props.selected_metric.name == "revenue"


def test_app_shell_runs_evaluation_suite() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FakeFrontendAppApiClient(),
    )

    state = shell.run_evaluation(
        eval_suite_id="frontend_smoke",
        questions=("Show revenue trend.",),
    )
    props = shell.evaluation_props()

    assert state.route is FrontendRoute.EVALUATION
    assert state.evaluation.latest_report is not None
    assert state.evaluation.latest_report.eval_suite_id == "frontend_smoke"
    assert state.evaluation.release_gate_status is ReleaseGateStatus.PASSED
    assert props.report is not None
    assert props.report.gate_label == "Release gate passed"
    assert props.report.tone == "success"


def test_app_shell_loads_task_status_page() -> None:
    api_client = FakeFrontendAppApiClient()
    shell = FrontendAppShell(context=_context(), api_client=api_client)

    state = shell.load_task_status("task_001")
    refreshed_state = shell.refresh_current_task_status()
    props = shell.task_status_props()

    assert state.route is FrontendRoute.TASK_STATUS
    assert state.task_status.current_status is not None
    assert state.task_status.current_status.status is UiTaskStatus.COMPLETED
    assert refreshed_state.route is FrontendRoute.TASK_STATUS
    assert props.status_card is not None
    assert props.status_card.task_id == "task_001"
    assert props.status_card.tone == "success"
    assert api_client.loaded_task_ids == ["task_001", "task_001"]


def test_app_shell_runs_analytics_page_workflows() -> None:
    api_client = FakeFrontendAppApiClient()
    shell = FrontendAppShell(context=_context(), api_client=api_client)
    request = _analytics_request("tr_analytics_shell")

    run_state = shell.run_analytics(request)
    run_props = shell.analytics_props()
    queued_state = shell.enqueue_analytics(request)
    loaded_state = shell.load_analytics_result("tr_analytics_shell")

    assert run_state.route is FrontendRoute.ANALYTICS
    assert run_state.analytics.latest_result is not None
    assert run_props.result is not None
    assert run_props.result.forecast_points_label == "Forecast points: 1"
    assert queued_state.analytics.latest_task is not None
    assert queued_state.analytics.latest_task.kind == "analytics"
    assert loaded_state.analytics.latest_result is not None
    assert api_client.analyzed_trace_ids == ["tr_analytics_shell"]
    assert api_client.enqueued_trace_ids == ["tr_analytics_shell"]
    assert api_client.loaded_analytics_trace_ids == ["tr_analytics_shell"]


def test_app_shell_sets_analytics_request_then_runs_current() -> None:
    api_client = FakeFrontendAppApiClient()
    shell = FrontendAppShell(context=_context(), api_client=api_client)

    shell.set_analytics_request(_analytics_request("tr_analytics_current"))
    state = shell.run_analytics()

    assert state.route is FrontendRoute.ANALYTICS
    assert state.analytics.request is not None
    assert state.analytics.request.trace_id == "tr_analytics_current"
    assert state.analytics.latest_result is not None
    assert api_client.analyzed_trace_ids == ["tr_analytics_current"]


def test_app_shell_noops_replay_when_no_history_selection_exists() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FakeFrontendAppApiClient(),
    )

    state = shell.replay_selected_history()

    assert state.route is FrontendRoute.CHAT
    assert state.chat.turns == ()


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )


def _result(trace_id: str) -> QueryResultViewModel:
    return QueryResultViewModel(
        trace_id=trace_id,
        answer=MessageBubbleViewModel(
            role=MessageRole.ASSISTANT,
            text="Revenue trend is ready.",
            trace_id=trace_id,
        ),
        warnings=(),
        table=TableCardViewModel(
            columns=("order_date", "revenue"),
            rows=({"order_date": "2026-06-18", "revenue": 1000},),
        ),
        chart=ChartCardViewModel(
            chart_type=ChartType.LINE,
            x_field="order_date",
            y_fields=("revenue",),
            title="Revenue Trend",
        ),
        analytics=None,
        evidence=(),
        sql_explain=SqlExplainCardViewModel(
            sql_text="SELECT order_date, revenue FROM daily_revenue",
            explanation="Generated SQL used by the governed query pipeline.",
        ),
        confidence=0.9,
    )


def _analytics_request(trace_id: str) -> FrontendAnalyticsRequest:
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


def _analytics_result(trace_id: str) -> FrontendAnalyticsResultViewModel:
    return FrontendAnalyticsResultViewModel(
        trace_id=trace_id,
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
    )
