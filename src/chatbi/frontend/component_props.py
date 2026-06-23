"""Screen component props for the ChatBI frontend.

State objects are good for business logic. UI components need labels, aria
text, stable component ids, and a predictable render order. This module builds
that last mile without tying the project to React, Vue, or any browser library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chatbi.core.contracts import Locale
from chatbi.frontend.chat_state import ChatPageState, ChatTurnStatus, ChatTurnViewModel
from chatbi.frontend.i18n import TranslationKey, translate
from chatbi.frontend.view_models import QueryResultViewModel, ResultBlockType


class ComponentId(StrEnum):
    CHAT_INPUT = "chat.input"
    CHAT_SEND = "chat.send"
    MESSAGE_LIST = "chat.message_list"
    RESULT_CARD = "chat.result_card"
    SQL_EXPLAIN = "result.sql_explain"


@dataclass(frozen=True, slots=True)
class ChatInputProps:
    placeholder: str
    send_label: str
    loading_label: str
    can_submit: bool
    aria_label: str


@dataclass(frozen=True, slots=True)
class ResultBlockProps:
    block_type: ResultBlockType
    title: str
    aria_label: str


@dataclass(frozen=True, slots=True)
class AnalyticsInsightProps:
    title: str
    model_label: str
    anomaly_label: str
    forecast_points_label: str
    narrative: tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class QueryResultCardProps:
    trace_id: str
    answer_text: str
    confidence_label: str
    blocks: tuple[ResultBlockProps, ...]
    has_partial_failure: bool
    analytics: AnalyticsInsightProps | None = None


@dataclass(frozen=True, slots=True)
class ChatTurnProps:
    question_text: str
    status: ChatTurnStatus
    result: QueryResultCardProps | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ChatPageProps:
    title: str
    empty_state: str
    input: ChatInputProps
    turns: tuple[ChatTurnProps, ...]
    is_loading: bool
    error_message: str | None
    tab_order: tuple[ComponentId, ...]


def build_chat_page_props(state: ChatPageState, locale: Locale) -> ChatPageProps:
    """Build framework-neutral props for the Chat page."""

    return ChatPageProps(
        title=translate(TranslationKey.APP_TITLE, locale),
        empty_state=translate(TranslationKey.CHAT_EMPTY_STATE, locale),
        input=ChatInputProps(
            placeholder=translate(TranslationKey.CHAT_INPUT_PLACEHOLDER, locale),
            send_label=translate(TranslationKey.CHAT_SEND, locale),
            loading_label=translate(TranslationKey.CHAT_LOADING, locale),
            can_submit=state.can_submit,
            aria_label=translate(TranslationKey.CHAT_INPUT_PLACEHOLDER, locale),
        ),
        turns=tuple(_turn_props(turn, locale) for turn in state.turns),
        is_loading=state.is_loading,
        error_message=state.error_message,
        tab_order=_tab_order_for(state),
    )


def should_submit_chat_input(
    key: str,
    shift_key: bool = False,
    is_composing: bool = False,
) -> bool:
    """Return True when a keyboard event should submit the chat input."""

    return key == "Enter" and not shift_key and not is_composing


def _turn_props(turn: ChatTurnViewModel, locale: Locale) -> ChatTurnProps:
    return ChatTurnProps(
        question_text=turn.question.text,
        status=turn.status,
        result=_result_card_props(turn.result, locale) if turn.result is not None else None,
        error_message=turn.error_message,
    )


def _result_card_props(
    result: QueryResultViewModel,
    locale: Locale,
) -> QueryResultCardProps:
    return QueryResultCardProps(
        trace_id=result.trace_id,
        answer_text=result.answer.text,
        confidence_label=translate(
            TranslationKey.RESULT_CONFIDENCE,
            locale,
            variables={"confidence": f"{result.confidence:.0%}"},
        ),
        blocks=tuple(_result_block_props(block_type, result, locale) for block_type in result.blocks),
        has_partial_failure=any(warning.is_partial_failure for warning in result.warnings),
        analytics=_analytics_insight_props(result, locale),
    )


def _result_block_props(
    block_type: ResultBlockType,
    result: QueryResultViewModel,
    locale: Locale,
) -> ResultBlockProps:
    if block_type is ResultBlockType.TABLE:
        title = translate(TranslationKey.RESULT_TABLE_TITLE, locale)
        return ResultBlockProps(block_type=block_type, title=title, aria_label=title)
    if block_type is ResultBlockType.CHART:
        title = translate(TranslationKey.RESULT_CHART_TITLE, locale)
        return ResultBlockProps(
            block_type=block_type,
            title=title,
            aria_label=_chart_aria_label(result, locale),
        )
    if block_type is ResultBlockType.ANALYTICS:
        title = translate(TranslationKey.RESULT_ANALYTICS_TITLE, locale)
        return ResultBlockProps(block_type=block_type, title=title, aria_label=title)
    if block_type is ResultBlockType.EVIDENCE:
        title = translate(TranslationKey.RESULT_EVIDENCE_TITLE, locale)
        return ResultBlockProps(block_type=block_type, title=title, aria_label=title)
    if block_type is ResultBlockType.SQL_EXPLAIN:
        title = translate(TranslationKey.RESULT_SQL_EXPLAIN, locale)
        return ResultBlockProps(block_type=block_type, title=title, aria_label=title)

    title = translate(TranslationKey.WARNING_PARTIAL_FAILURE, locale)
    return ResultBlockProps(block_type=block_type, title=title, aria_label=title)


def _chart_aria_label(result: QueryResultViewModel, locale: Locale) -> str:
    if result.chart is None:
        return translate(TranslationKey.RESULT_CHART_TITLE, locale)
    return translate(
        TranslationKey.ACCESSIBILITY_CHART_SUMMARY,
        locale,
        variables={
            "chart_type": result.chart.chart_type.value,
            "x_field": result.chart.x_field,
        },
    )


def _analytics_insight_props(
    result: QueryResultViewModel,
    locale: Locale,
) -> AnalyticsInsightProps | None:
    analytics = result.analytics
    if analytics is None:
        return None

    return AnalyticsInsightProps(
        title=translate(TranslationKey.RESULT_ANALYTICS_TITLE, locale),
        model_label=translate(
            TranslationKey.RESULT_ANALYTICS_MODEL,
            locale,
            variables={"model": analytics.model_used},
        ),
        anomaly_label=translate(
            TranslationKey.RESULT_ANALYTICS_ANOMALY,
            locale,
            variables={"level": analytics.anomaly_level},
        ),
        forecast_points_label=translate(
            TranslationKey.RESULT_ANALYTICS_FORECAST_POINTS,
            locale,
            variables={"count": analytics.forecast_points},
        ),
        narrative=(
            analytics.fact,
            analytics.judgment,
            analytics.uncertainty,
        ),
    )


def _tab_order_for(state: ChatPageState) -> tuple[ComponentId, ...]:
    order = [
        ComponentId.CHAT_INPUT,
        ComponentId.CHAT_SEND,
        ComponentId.MESSAGE_LIST,
    ]
    if any(turn.result is not None for turn in state.turns):
        order.extend((ComponentId.RESULT_CARD, ComponentId.SQL_EXPLAIN))
    return tuple(order)
