"""Screen component props for the ChatBI frontend.

State objects are good for business logic. UI components need labels, aria
text, stable component ids, and a predictable render order. This module builds
that last mile without tying the project to React, Vue, or any browser library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chatbi.core.contracts import Locale
from chatbi.frontend.catalog_state import (
    CatalogPageState,
    MetricDefinitionViewModel,
)
from chatbi.frontend.analytics_state import AnalyticsPageState
from chatbi.frontend.chat_state import ChatPageState, ChatTurnStatus, ChatTurnViewModel
from chatbi.frontend.evaluation_state import EvaluationPageState, ReleaseGateStatus
from chatbi.frontend.history_state import (
    HistoryItemStatus,
    HistoryItemViewModel,
    HistoryPageState,
)
from chatbi.frontend.i18n import TranslationKey, translate
from chatbi.frontend.task_status_page_state import TaskStatusPageState
from chatbi.frontend.task_status_state import TaskStatusViewModel, UiTaskStatus
from chatbi.frontend.ui_answer_state import UiAnswerState
from chatbi.frontend.view_models import QueryResultViewModel, ResultBlockType


class ComponentId(StrEnum):
    NAV_CHAT = "nav.chat"
    NAV_HISTORY = "nav.history"
    NAV_CATALOG = "nav.catalog"
    NAV_ANALYTICS = "nav.analytics"
    NAV_TASK_STATUS = "nav.task_status"
    NAV_EVALUATION = "nav.evaluation"
    CHAT_INPUT = "chat.input"
    CHAT_SEND = "chat.send"
    MESSAGE_LIST = "chat.message_list"
    ERROR_BOUNDARY = "error.boundary"
    RESULT_CARD = "chat.result_card"
    TRACE_ID = "trace.id"
    TRACE_COPY = "trace.copy"
    SQL_EXPLAIN = "result.sql_explain"
    TASK_STATUS_INPUT = "task.status.input"
    TASK_STATUS_LOAD = "task.status.load"
    TASK_STATUS_REFRESH = "task.status.refresh"
    TASK_STATUS_CARD = "task.status.card"
    HISTORY_LIST = "history.list"
    HISTORY_LOAD_MORE = "history.load_more"
    HISTORY_REPLAY = "history.replay"
    CATALOG_SEARCH = "catalog.search"
    CATALOG_LIST = "catalog.list"
    CATALOG_DETAIL = "catalog.detail"
    EVALUATION_SUITE = "evaluation.suite"
    EVALUATION_RUN = "evaluation.run"
    EVALUATION_REPORT = "evaluation.report"
    EVALUATION_FAILED_CASES = "evaluation.failed_cases"
    ANALYTICS_RUN = "analytics.run"
    ANALYTICS_ENQUEUE = "analytics.enqueue"
    ANALYTICS_LOAD_RESULT = "analytics.load_result"
    ANALYTICS_RESULT = "analytics.result"
    ANALYTICS_TASK = "analytics.task"


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
class TraceIdProps:
    trace_id: str
    label: str
    copy_label: str
    copy_value: str
    copyable: bool


@dataclass(frozen=True, slots=True)
class ErrorBoundaryProps:
    code: str
    title: str
    message: str
    retry_label: str
    retryable: bool


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
    answer_state: UiAnswerState
    trace: TraceIdProps | None
    error_boundary: ErrorBoundaryProps | None
    turns: tuple[ChatTurnProps, ...]
    is_loading: bool
    error_message: str | None
    tab_order: tuple[ComponentId, ...]


@dataclass(frozen=True, slots=True)
class HistoryItemProps:
    trace_id: str
    question_text: str
    status: HistoryItemStatus
    status_label: str
    created_at: str
    replay_label: str
    can_replay: bool
    is_selected: bool


@dataclass(frozen=True, slots=True)
class HistoryPageProps:
    title: str
    empty_state: str
    items: tuple[HistoryItemProps, ...]
    load_more_label: str
    can_load_more: bool
    selected_trace_id: str | None
    is_loading: bool
    error_message: str | None
    tab_order: tuple[ComponentId, ...]


@dataclass(frozen=True, slots=True)
class CatalogSearchProps:
    value: str
    placeholder: str
    aria_label: str


@dataclass(frozen=True, slots=True)
class CatalogMetricProps:
    name: str
    sql_definition: str
    source_tables: tuple[str, ...]
    semantic_version: str
    is_selected: bool


@dataclass(frozen=True, slots=True)
class CatalogSelectedMetricProps:
    title: str
    name: str
    sql_definition: str
    source_tables_label: str
    semantic_version_label: str


@dataclass(frozen=True, slots=True)
class CatalogPageProps:
    title: str
    empty_state: str
    search: CatalogSearchProps
    metrics: tuple[CatalogMetricProps, ...]
    selected_metric: CatalogSelectedMetricProps | None
    is_loading: bool
    error_message: str | None
    tab_order: tuple[ComponentId, ...]


@dataclass(frozen=True, slots=True)
class EvaluationRunInputProps:
    eval_suite_id: str
    question_count: int
    run_label: str
    running_label: str
    can_run: bool
    aria_label: str


@dataclass(frozen=True, slots=True)
class EvaluationFailedCaseProps:
    question: str
    trace_id: str | None
    error_code: str | None
    score_label: str


@dataclass(frozen=True, slots=True)
class EvaluationReportProps:
    eval_run_id: str
    eval_suite_id: str
    gate_status: ReleaseGateStatus
    gate_label: str
    tone: str
    score_label: str
    cases_label: str
    failed_cases_label: str
    failed_cases: tuple[EvaluationFailedCaseProps, ...]


@dataclass(frozen=True, slots=True)
class EvaluationPageProps:
    title: str
    empty_state: str
    input: EvaluationRunInputProps
    report: EvaluationReportProps | None
    is_running: bool
    error_message: str | None
    tab_order: tuple[ComponentId, ...]


@dataclass(frozen=True, slots=True)
class AnalyticsRunInputProps:
    trace_id: str
    metric_id: str
    grain: str
    row_count: int
    run_label: str
    enqueue_label: str
    load_result_label: str
    can_run: bool
    can_enqueue: bool
    can_load_result: bool
    aria_label: str


@dataclass(frozen=True, slots=True)
class AnalyticsResultSummaryProps:
    trace_id: str
    metric_id: str
    method_label: str
    model_version_label: str
    forecast_points_label: str
    warning_count_label: str
    explanation: str


@dataclass(frozen=True, slots=True)
class AnalyticsPageProps:
    title: str
    empty_state: str
    input: AnalyticsRunInputProps
    result: AnalyticsResultSummaryProps | None
    task: TaskStatusCardProps | None
    is_loading: bool
    error_message: str | None
    tab_order: tuple[ComponentId, ...]


@dataclass(frozen=True, slots=True)
class TaskStatusInputProps:
    value: str
    placeholder: str
    load_label: str
    refresh_label: str
    can_load: bool
    can_refresh: bool
    aria_label: str


@dataclass(frozen=True, slots=True)
class TaskStatusCardProps:
    task_id: str
    trace_id: str
    kind: str
    status: UiTaskStatus
    label: str
    tone: str
    is_terminal: bool
    result_count_label: str
    error_message: str | None


@dataclass(frozen=True, slots=True)
class TaskStatusPageProps:
    title: str
    empty_state: str
    input: TaskStatusInputProps
    status_card: TaskStatusCardProps | None
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
        answer_state=state.answer_state,
        trace=_trace_id_props(state.answer_state.trace_id, locale),
        error_boundary=_error_boundary_props(state.answer_state.error_code, locale),
        turns=tuple(_turn_props(turn, locale) for turn in state.turns),
        is_loading=state.is_loading,
        error_message=state.error_message,
        tab_order=_tab_order_for(state),
    )


def build_history_page_props(
    state: HistoryPageState,
    locale: Locale,
) -> HistoryPageProps:
    return HistoryPageProps(
        title=translate(TranslationKey.HISTORY_TITLE, locale),
        empty_state=translate(TranslationKey.HISTORY_EMPTY, locale),
        items=tuple(_history_item_props(item, state, locale) for item in state.items),
        load_more_label=translate(TranslationKey.HISTORY_LOAD_MORE, locale),
        can_load_more=state.has_more and not state.is_loading,
        selected_trace_id=None
        if state.selected_replay is None
        else state.selected_replay.trace_id,
        is_loading=state.is_loading,
        error_message=state.error_message,
        tab_order=_history_tab_order_for(state),
    )


def build_catalog_page_props(
    state: CatalogPageState,
    locale: Locale,
) -> CatalogPageProps:
    return CatalogPageProps(
        title=translate(TranslationKey.CATALOG_TITLE, locale),
        empty_state=translate(TranslationKey.CATALOG_EMPTY, locale),
        search=CatalogSearchProps(
            value=state.search_query,
            placeholder=translate(TranslationKey.CATALOG_SEARCH_PLACEHOLDER, locale),
            aria_label=translate(TranslationKey.CATALOG_SEARCH_PLACEHOLDER, locale),
        ),
        metrics=tuple(
            _catalog_metric_props(metric, state)
            for metric in state.filtered_metrics
        ),
        selected_metric=_catalog_selected_metric_props(state.selected_metric, locale),
        is_loading=state.is_loading,
        error_message=state.error_message,
        tab_order=_catalog_tab_order_for(state),
    )


def build_evaluation_page_props(
    state: EvaluationPageState,
    locale: Locale,
) -> EvaluationPageProps:
    return EvaluationPageProps(
        title=translate(TranslationKey.EVALUATION_TITLE, locale),
        empty_state=translate(TranslationKey.EVALUATION_EMPTY, locale),
        input=EvaluationRunInputProps(
            eval_suite_id=state.eval_suite_id,
            question_count=len(state.questions),
            run_label=translate(TranslationKey.EVALUATION_RUN, locale),
            running_label=translate(TranslationKey.EVALUATION_RUNNING, locale),
            can_run=bool(state.eval_suite_id.strip()) and not state.is_running,
            aria_label=translate(TranslationKey.EVALUATION_RUN, locale),
        ),
        report=_evaluation_report_props(state, locale),
        is_running=state.is_running,
        error_message=state.error_message,
        tab_order=_evaluation_tab_order_for(state),
    )


def build_analytics_page_props(
    state: AnalyticsPageState,
    locale: Locale,
) -> AnalyticsPageProps:
    request = state.request
    has_request = request is not None
    return AnalyticsPageProps(
        title=translate(TranslationKey.ANALYTICS_TITLE, locale),
        empty_state=translate(TranslationKey.ANALYTICS_EMPTY, locale),
        input=AnalyticsRunInputProps(
            trace_id="" if request is None else request.trace_id,
            metric_id="" if request is None else request.metric_id,
            grain="" if request is None else request.grain,
            row_count=0 if request is None else len(request.rows),
            run_label=translate(TranslationKey.ANALYTICS_RUN, locale),
            enqueue_label=translate(TranslationKey.ANALYTICS_ENQUEUE, locale),
            load_result_label=translate(TranslationKey.ANALYTICS_LOAD_RESULT, locale),
            can_run=has_request and not state.is_loading,
            can_enqueue=has_request and not state.is_loading,
            can_load_result=has_request and bool(request.trace_id.strip()) and not state.is_loading,
            aria_label=translate(TranslationKey.ANALYTICS_TITLE, locale),
        ),
        result=_analytics_result_summary_props(state, locale),
        task=_task_status_card_props(state.latest_task, locale),
        is_loading=state.is_loading,
        error_message=state.error_message,
        tab_order=_analytics_tab_order_for(state),
    )


def build_task_status_page_props(
    state: TaskStatusPageState,
    locale: Locale,
) -> TaskStatusPageProps:
    return TaskStatusPageProps(
        title=translate(TranslationKey.TASK_STATUS_TITLE, locale),
        empty_state=translate(TranslationKey.TASK_STATUS_EMPTY, locale),
        input=TaskStatusInputProps(
            value=state.task_id or "",
            placeholder=translate(TranslationKey.TASK_STATUS_INPUT_PLACEHOLDER, locale),
            load_label=translate(TranslationKey.TASK_STATUS_LOAD, locale),
            refresh_label=translate(TranslationKey.TASK_STATUS_REFRESH, locale),
            can_load=bool((state.task_id or "").strip()) and not state.is_loading,
            can_refresh=state.current_status is not None and not state.is_loading,
            aria_label=translate(TranslationKey.TASK_STATUS_INPUT_PLACEHOLDER, locale),
        ),
        status_card=_task_status_card_props(state.current_status, locale),
        is_loading=state.is_loading,
        error_message=state.error_message,
        tab_order=_task_status_tab_order_for(state),
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


def _history_item_props(
    item: HistoryItemViewModel,
    state: HistoryPageState,
    locale: Locale,
) -> HistoryItemProps:
    return HistoryItemProps(
        trace_id=item.trace_id,
        question_text=item.question,
        status=item.status,
        status_label=_history_status_label(item.status, locale),
        created_at=item.created_at,
        replay_label=translate(TranslationKey.HISTORY_REPLAY, locale),
        can_replay=item.can_replay and not state.is_loading,
        is_selected=(
            state.selected_replay is not None
            and state.selected_replay.trace_id == item.trace_id
        ),
    )


def _history_status_label(status: HistoryItemStatus, locale: Locale) -> str:
    if status is HistoryItemStatus.SUCCEEDED:
        return translate(TranslationKey.HISTORY_STATUS_SUCCEEDED, locale)
    return translate(TranslationKey.HISTORY_STATUS_FAILED, locale)


def _catalog_metric_props(
    metric: MetricDefinitionViewModel,
    state: CatalogPageState,
) -> CatalogMetricProps:
    return CatalogMetricProps(
        name=metric.name,
        sql_definition=metric.sql_definition,
        source_tables=metric.source_tables,
        semantic_version=metric.semantic_version,
        is_selected=metric.name == state.selected_metric_name,
    )


def _catalog_selected_metric_props(
    metric: MetricDefinitionViewModel | None,
    locale: Locale,
) -> CatalogSelectedMetricProps | None:
    if metric is None:
        return None
    return CatalogSelectedMetricProps(
        title=translate(TranslationKey.CATALOG_SELECTED_TITLE, locale),
        name=metric.name,
        sql_definition=metric.sql_definition,
        source_tables_label=translate(
            TranslationKey.CATALOG_SOURCE_TABLES,
            locale,
            variables={"tables": ", ".join(metric.source_tables)},
        ),
        semantic_version_label=translate(
            TranslationKey.CATALOG_SEMANTIC_VERSION,
            locale,
            variables={"version": metric.semantic_version},
        ),
    )


def _evaluation_report_props(
    state: EvaluationPageState,
    locale: Locale,
) -> EvaluationReportProps | None:
    report = state.latest_report
    if report is None:
        return None
    failed_cases = tuple(
        EvaluationFailedCaseProps(
            question=str(raw_case.get("question", "")),
            trace_id=_optional_str(raw_case.get("trace_id")),
            error_code=_optional_str(raw_case.get("error_code")),
            score_label=translate(
                TranslationKey.EVALUATION_SCORE,
                locale,
                variables={"score": f"{float(raw_case.get('score', 0.0)):.0%}"},
            ),
        )
        for raw_case in report.failed_cases_detail
    )
    return EvaluationReportProps(
        eval_run_id=report.eval_run_id,
        eval_suite_id=report.eval_suite_id,
        gate_status=state.release_gate_status,
        gate_label=_evaluation_gate_label(state.release_gate_status, locale),
        tone=_evaluation_tone(state.release_gate_status),
        score_label=translate(
            TranslationKey.EVALUATION_SCORE,
            locale,
            variables={"score": f"{report.overall_score:.0%}"},
        ),
        cases_label=translate(
            TranslationKey.EVALUATION_CASES,
            locale,
            variables={
                "passed": report.passed_cases,
                "total": report.total_cases,
            },
        ),
        failed_cases_label=translate(
            TranslationKey.EVALUATION_FAILED_CASES,
            locale,
            variables={"count": report.failed_cases},
        ),
        failed_cases=failed_cases,
    )


def _evaluation_gate_label(status: ReleaseGateStatus, locale: Locale) -> str:
    if status is ReleaseGateStatus.PASSED:
        return translate(TranslationKey.EVALUATION_GATE_PASSED, locale)
    if status is ReleaseGateStatus.FAILED:
        return translate(TranslationKey.EVALUATION_GATE_FAILED, locale)
    return translate(TranslationKey.EVALUATION_GATE_NOT_RUN, locale)


def _evaluation_tone(status: ReleaseGateStatus) -> str:
    if status is ReleaseGateStatus.PASSED:
        return "success"
    if status is ReleaseGateStatus.FAILED:
        return "danger"
    return "neutral"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


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


def _trace_id_props(trace_id: str | None, locale: Locale) -> TraceIdProps | None:
    if trace_id is None:
        return None
    return TraceIdProps(
        trace_id=trace_id,
        label=translate(
            TranslationKey.TRACE_ID_LABEL,
            locale,
            variables={"trace_id": trace_id},
        ),
        copy_label=translate(TranslationKey.TRACE_COPY, locale),
        copy_value=trace_id,
        copyable=True,
    )


def _error_boundary_props(error_code: str | None, locale: Locale) -> ErrorBoundaryProps | None:
    if error_code is None:
        return None

    title_key, message_key, retryable = _error_boundary_copy(error_code)
    return ErrorBoundaryProps(
        code=error_code,
        title=translate(title_key, locale),
        message=translate(message_key, locale),
        retry_label=translate(TranslationKey.ERROR_RETRY, locale),
        retryable=retryable,
    )


def _error_boundary_copy(error_code: str) -> tuple[TranslationKey, TranslationKey, bool]:
    if error_code == "VALIDATION_ERROR":
        return (
            TranslationKey.ERROR_VALIDATION_TITLE,
            TranslationKey.ERROR_VALIDATION_MESSAGE,
            True,
        )
    if error_code == "SQL_GUARDRAIL_DENIED":
        return (
            TranslationKey.ERROR_SQL_GUARDRAIL_TITLE,
            TranslationKey.ERROR_SQL_GUARDRAIL_MESSAGE,
            True,
        )
    return (
        TranslationKey.ERROR_INTERNAL_TITLE,
        TranslationKey.ERROR_INTERNAL_MESSAGE,
        True,
    )


def _tab_order_for(state: ChatPageState) -> tuple[ComponentId, ...]:
    order = [
        ComponentId.CHAT_INPUT,
        ComponentId.CHAT_SEND,
        ComponentId.MESSAGE_LIST,
    ]
    if state.answer_state.error_code is not None:
        order.append(ComponentId.ERROR_BOUNDARY)
    if any(turn.result is not None for turn in state.turns):
        order.append(ComponentId.RESULT_CARD)
        if state.answer_state.trace_id is not None:
            order.extend((ComponentId.TRACE_ID, ComponentId.TRACE_COPY))
        order.append(ComponentId.SQL_EXPLAIN)
    return tuple(order)


def _task_status_card_props(
    status: TaskStatusViewModel | None,
    locale: Locale,
) -> TaskStatusCardProps | None:
    if status is None:
        return None
    return TaskStatusCardProps(
        task_id=status.task_id,
        trace_id=status.trace_id,
        kind=status.kind,
        status=status.status,
        label=status.label,
        tone=_task_status_tone(status),
        is_terminal=status.is_terminal,
        result_count_label=translate(
            TranslationKey.TASK_STATUS_RESULT_COUNT,
            locale,
            variables={"count": len(status.result)},
        ),
        error_message=status.error_message,
    )


def _task_status_tone(status: TaskStatusViewModel) -> str:
    if status.status is UiTaskStatus.FAILED:
        return "danger"
    if status.status is UiTaskStatus.PARTIAL:
        return "warning"
    if status.status is UiTaskStatus.COMPLETED:
        return "success"
    return "neutral"


def _analytics_result_summary_props(
    state: AnalyticsPageState,
    locale: Locale,
) -> AnalyticsResultSummaryProps | None:
    result = state.latest_result
    if result is None:
        return None
    return AnalyticsResultSummaryProps(
        trace_id=result.trace_id,
        metric_id=result.metric_id,
        method_label=translate(
            TranslationKey.ANALYTICS_METHOD,
            locale,
            variables={"method": result.method},
        ),
        model_version_label=translate(
            TranslationKey.ANALYTICS_MODEL_VERSION,
            locale,
            variables={"model_version": result.model_version},
        ),
        forecast_points_label=translate(
            TranslationKey.ANALYTICS_FORECAST_POINTS,
            locale,
            variables={"count": len(result.forecast_points)},
        ),
        warning_count_label=translate(
            TranslationKey.ANALYTICS_WARNINGS,
            locale,
            variables={"count": len(result.quality_warnings)},
        ),
        explanation=result.explanation,
    )


def _analytics_tab_order_for(state: AnalyticsPageState) -> tuple[ComponentId, ...]:
    order = [
        ComponentId.ANALYTICS_RUN,
        ComponentId.ANALYTICS_ENQUEUE,
        ComponentId.ANALYTICS_LOAD_RESULT,
    ]
    if state.latest_result is not None:
        order.append(ComponentId.ANALYTICS_RESULT)
    if state.latest_task is not None:
        order.append(ComponentId.ANALYTICS_TASK)
    return tuple(order)


def _task_status_tab_order_for(state: TaskStatusPageState) -> tuple[ComponentId, ...]:
    order = [
        ComponentId.TASK_STATUS_INPUT,
        ComponentId.TASK_STATUS_LOAD,
    ]
    if state.current_status is not None:
        order.extend((ComponentId.TASK_STATUS_REFRESH, ComponentId.TASK_STATUS_CARD))
    return tuple(order)


def _history_tab_order_for(state: HistoryPageState) -> tuple[ComponentId, ...]:
    order = [ComponentId.HISTORY_LIST]
    if any(item.can_replay for item in state.items):
        order.append(ComponentId.HISTORY_REPLAY)
    if state.has_more:
        order.append(ComponentId.HISTORY_LOAD_MORE)
    return tuple(order)


def _catalog_tab_order_for(state: CatalogPageState) -> tuple[ComponentId, ...]:
    order = [ComponentId.CATALOG_SEARCH]
    if state.filtered_metrics:
        order.append(ComponentId.CATALOG_LIST)
    if state.selected_metric is not None:
        order.append(ComponentId.CATALOG_DETAIL)
    return tuple(order)


def _evaluation_tab_order_for(state: EvaluationPageState) -> tuple[ComponentId, ...]:
    order = [
        ComponentId.EVALUATION_SUITE,
        ComponentId.EVALUATION_RUN,
    ]
    if state.latest_report is not None:
        order.append(ComponentId.EVALUATION_REPORT)
        if state.latest_report.failed_cases_detail:
            order.append(ComponentId.EVALUATION_FAILED_CASES)
    return tuple(order)
