from chatbi.core.contracts import ChartType, Locale, UserRole
from chatbi.frontend.api_client import (
    EvaluationRunViewModel,
    FrontendUserContext,
    HistoryListViewModel,
    MetricCatalogViewModel,
)
from chatbi.frontend.app_shell import FrontendAppShell, FrontendRoute
from chatbi.frontend.chat_state import ChatTurnStatus
from chatbi.frontend.evaluation_state import ReleaseGateStatus
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


def test_app_shell_submits_chat_question_and_builds_chat_props() -> None:
    api_client = FakeFrontendAppApiClient()
    shell = FrontendAppShell(context=_context(), api_client=api_client)

    state = shell.submit_chat_question("Show revenue trend.")
    props = shell.chat_props()

    assert state.route is FrontendRoute.CHAT
    assert state.chat.turns[0].status is ChatTurnStatus.ANSWERED
    assert api_client.submitted_questions == ["Show revenue trend."]
    assert props.turns[0].result is not None
    assert props.turns[0].result.answer_text == "Revenue trend is ready."


def test_app_shell_loads_history_selects_and_replays_into_chat() -> None:
    api_client = FakeFrontendAppApiClient()
    shell = FrontendAppShell(context=_context(), api_client=api_client)

    history_state = shell.load_history()
    selected_state = shell.select_history_for_replay("trc_history")
    replay_state = shell.replay_selected_history()

    assert history_state.route is FrontendRoute.HISTORY
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

    assert loaded_state.route is FrontendRoute.CATALOG
    assert loaded_state.catalog.selected_metric is not None
    assert loaded_state.catalog.selected_metric.name == "revenue"
    assert [metric.name for metric in searched_state.catalog.filtered_metrics] == ["revenue"]


def test_app_shell_runs_evaluation_suite() -> None:
    shell = FrontendAppShell(
        context=_context(),
        api_client=FakeFrontendAppApiClient(),
    )

    state = shell.run_evaluation(
        eval_suite_id="frontend_smoke",
        questions=("Show revenue trend.",),
    )

    assert state.route is FrontendRoute.EVALUATION
    assert state.evaluation.latest_report is not None
    assert state.evaluation.latest_report.eval_suite_id == "frontend_smoke"
    assert state.evaluation.release_gate_status is ReleaseGateStatus.PASSED


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
