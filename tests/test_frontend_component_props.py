from chatbi.core.contracts import ChartType, Locale, UserRole
from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.chat_state import ChatPageState, ChatTurnStatus, ChatTurnViewModel
from chatbi.frontend.component_props import (
    ComponentId,
    build_chat_page_props,
    should_submit_chat_input,
)
from chatbi.frontend.view_models import (
    AnalyticsCardViewModel,
    ChartCardViewModel,
    MessageBubbleViewModel,
    MessageRole,
    QueryResultViewModel,
    ResultBlockType,
    SqlExplainCardViewModel,
    TableCardViewModel,
    WarningBannerViewModel,
)


def test_build_chat_page_props_returns_localized_empty_state() -> None:
    state = ChatPageState(context=_context(locale=Locale.ZH_CN))

    props = build_chat_page_props(state, Locale.ZH_CN)

    assert props.title == "InsightOps AI"
    assert props.empty_state == "可以从收入、订单、用户或异常波动开始提问。"
    assert props.input.placeholder == "请输入一个业务问题..."
    assert props.input.send_label == "发送"
    assert props.input.can_submit is True
    assert props.turns == ()
    assert props.tab_order == (
        ComponentId.CHAT_INPUT,
        ComponentId.CHAT_SEND,
        ComponentId.MESSAGE_LIST,
    )


def test_build_chat_page_props_includes_result_blocks_and_accessibility_labels() -> None:
    state = ChatPageState(
        context=_context(),
        turns=(
            ChatTurnViewModel(
                question=MessageBubbleViewModel(
                    role=MessageRole.USER,
                    text="Show revenue trend.",
                ),
                status=ChatTurnStatus.ANSWERED,
                result=_result(),
            ),
        ),
    )

    props = build_chat_page_props(state, Locale.EN)

    assert props.turns[0].question_text == "Show revenue trend."
    assert props.turns[0].result is not None
    assert props.turns[0].result.confidence_label == "Confidence: 91%"
    assert props.turns[0].result.has_partial_failure is True
    assert [block.block_type for block in props.turns[0].result.blocks] == [
        ResultBlockType.WARNING,
        ResultBlockType.TABLE,
        ResultBlockType.CHART,
        ResultBlockType.SQL_EXPLAIN,
    ]
    assert props.turns[0].result.blocks[2].aria_label == "line chart with x field order_date."
    assert props.tab_order == (
        ComponentId.CHAT_INPUT,
        ComponentId.CHAT_SEND,
        ComponentId.MESSAGE_LIST,
        ComponentId.RESULT_CARD,
        ComponentId.SQL_EXPLAIN,
    )


def test_build_chat_page_props_includes_analytics_insight_props() -> None:
    state = ChatPageState(
        context=_context(),
        turns=(
            ChatTurnViewModel(
                question=MessageBubbleViewModel(
                    role=MessageRole.USER,
                    text="Predict revenue for next month.",
                ),
                status=ChatTurnStatus.ANSWERED,
                result=_result_with_analytics(),
            ),
        ),
    )

    props = build_chat_page_props(state, Locale.EN)

    result = props.turns[0].result
    assert result is not None
    assert result.analytics is not None
    assert result.analytics.title == "Analytics"
    assert result.analytics.model_label == "Model: moving_average"
    assert result.analytics.anomaly_label == "Anomaly level: none"
    assert result.analytics.forecast_points_label == "Forecast points: 3"
    assert result.analytics.narrative == (
        "Revenue latest value is 1350.00 at 2026-06.",
        "moving_average projects the next value near 1283.33.",
        "The first-step confidence interval is 1168.11 to 1398.55.",
    )
    assert [block.block_type for block in result.blocks] == [
        ResultBlockType.TABLE,
        ResultBlockType.CHART,
        ResultBlockType.ANALYTICS,
        ResultBlockType.SQL_EXPLAIN,
    ]


def test_build_chat_page_props_localizes_analytics_labels() -> None:
    state = ChatPageState(
        context=_context(locale=Locale.ZH_CN),
        turns=(
            ChatTurnViewModel(
                question=MessageBubbleViewModel(
                    role=MessageRole.USER,
                    text="预测下个月收入。",
                ),
                status=ChatTurnStatus.ANSWERED,
                result=_result_with_analytics(),
            ),
        ),
    )

    props = build_chat_page_props(state, Locale.ZH_CN)

    result = props.turns[0].result
    assert result is not None
    assert result.analytics is not None
    assert result.analytics.title == "分析"
    assert result.analytics.model_label == "模型：moving_average"
    assert result.analytics.anomaly_label == "异常等级：none"
    assert result.analytics.forecast_points_label == "预测点数：3"


def test_build_chat_page_props_disables_submit_while_loading() -> None:
    state = ChatPageState(context=_context(), is_loading=True)

    props = build_chat_page_props(state, Locale.EN)

    assert props.is_loading is True
    assert props.input.can_submit is False
    assert props.input.loading_label == "Analyzing your question..."


def test_should_submit_chat_input_supports_keyboard_submission() -> None:
    assert should_submit_chat_input("Enter") is True
    assert should_submit_chat_input("Enter", shift_key=True) is False
    assert should_submit_chat_input("Enter", is_composing=True) is False
    assert should_submit_chat_input("Escape") is False


def _context(locale: Locale = Locale.EN) -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=locale,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )


def _result() -> QueryResultViewModel:
    return QueryResultViewModel(
        trace_id="trc_result",
        answer=MessageBubbleViewModel(
            role=MessageRole.ASSISTANT,
            text="Revenue trend is ready.",
            trace_id="trc_result",
        ),
        warnings=(
            WarningBannerViewModel(
                code="AGENT_PARTIAL_FAILURE",
                message="Some agents failed.",
                is_partial_failure=True,
            ),
        ),
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
        confidence=0.91,
    )


def _result_with_analytics() -> QueryResultViewModel:
    return QueryResultViewModel(
        trace_id="trc_result",
        answer=MessageBubbleViewModel(
            role=MessageRole.ASSISTANT,
            text="Revenue forecast is ready.",
            trace_id="trc_result",
        ),
        warnings=(),
        table=TableCardViewModel(
            columns=("month", "revenue"),
            rows=({"month": "2026-06", "revenue": 1350},),
        ),
        chart=ChartCardViewModel(
            chart_type=ChartType.LINE,
            x_field="month",
            y_fields=("revenue",),
            title="Revenue Trend",
        ),
        analytics=AnalyticsCardViewModel(
            model_used="moving_average",
            anomaly_level="none",
            forecast_points=3,
            fact="Revenue latest value is 1350.00 at 2026-06.",
            judgment="moving_average projects the next value near 1283.33.",
            uncertainty="The first-step confidence interval is 1168.11 to 1398.55.",
        ),
        evidence=(),
        sql_explain=SqlExplainCardViewModel(
            sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
            explanation="Generated SQL used by the governed query pipeline.",
        ),
        confidence=0.86,
    )
