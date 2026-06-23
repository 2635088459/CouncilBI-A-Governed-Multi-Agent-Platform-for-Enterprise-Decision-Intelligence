from chatbi.core.contracts import ChartType, Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.chat_state import ChatSessionStore, ChatTurnStatus
from chatbi.frontend.view_models import (
    ChartCardViewModel,
    MessageBubbleViewModel,
    MessageRole,
    QueryResultViewModel,
    SqlExplainCardViewModel,
    TableCardViewModel,
)


class FakeChatApiClient:
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
        return _result(trace_id=f"trc_{len(self.submitted_questions)}")

    def replay_query(
        self,
        context: FrontendUserContext,
        trace_id: str,
    ) -> QueryResultViewModel:
        self.replayed_trace_ids.append(trace_id)
        return _result(trace_id=trace_id)


class ErrorChatApiClient(FakeChatApiClient):
    def submit_question(
        self,
        context: FrontendUserContext,
        question: str,
        idempotency_key: str | None = None,
    ) -> QueryResultViewModel:
        raise ValueError("Backend API request failed.")


def test_submit_question_adds_user_turn_and_answer_result() -> None:
    api_client = FakeChatApiClient()
    store = ChatSessionStore(context=_context(), api_client=api_client)

    state = store.submit_question("  Show revenue trend.  ")

    assert state.is_loading is False
    assert state.error_message is None
    assert state.turns[0].question.role is MessageRole.USER
    assert state.turns[0].question.text == "Show revenue trend."
    assert state.turns[0].status is ChatTurnStatus.ANSWERED
    assert state.turns[0].result is not None
    assert state.turns[0].result.trace_id == "trc_1"
    assert api_client.submitted_questions == ["Show revenue trend."]


def test_submit_question_keeps_same_session_for_followups() -> None:
    api_client = FakeChatApiClient()
    store = ChatSessionStore(context=_context(), api_client=api_client)

    first_state = store.submit_question("Show revenue trend.")
    second_state = store.submit_question("What changed last month?")

    assert first_state.context.session_id == "s_001"
    assert second_state.context.session_id == "s_001"
    assert len(second_state.turns) == 2
    assert api_client.submitted_questions == [
        "Show revenue trend.",
        "What changed last month?",
    ]


def test_submit_question_records_failure_without_losing_user_question() -> None:
    store = ChatSessionStore(context=_context(), api_client=ErrorChatApiClient())

    state = store.submit_question("DROP TABLE orders")

    assert state.is_loading is False
    assert state.error_message == "Backend API request failed."
    assert state.turns[0].question.text == "DROP TABLE orders"
    assert state.turns[0].status is ChatTurnStatus.FAILED
    assert state.turns[0].result is None


def test_replay_history_item_appends_replayed_turn() -> None:
    api_client = FakeChatApiClient()
    store = ChatSessionStore(context=_context(), api_client=api_client)

    state = store.replay_history_item(
        trace_id="trc_history_001",
        question="Show revenue trend.",
    )

    assert state.is_loading is False
    assert state.turns[0].status is ChatTurnStatus.REPLAYED
    assert state.turns[0].question.trace_id == "trc_history_001"
    assert state.turns[0].result is not None
    assert state.turns[0].result.trace_id == "trc_history_001"
    assert api_client.replayed_trace_ids == ["trc_history_001"]


def test_submit_question_rejects_empty_question_before_api_call() -> None:
    api_client = FakeChatApiClient()
    store = ChatSessionStore(context=_context(), api_client=api_client)

    try:
        store.submit_question("  ")
    except ValueError as exc:
        assert str(exc) == "Question is required."
    else:
        raise AssertionError("Expected empty question to fail.")

    assert api_client.submitted_questions == []
    assert store.state.turns == ()


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
