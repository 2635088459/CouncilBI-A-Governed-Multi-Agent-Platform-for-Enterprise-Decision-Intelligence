"""Frontend i18n dictionary for the ChatBI experience.

Think of this file as the UI's phrasebook. Components should ask this module
for display text instead of hard-coding Chinese or English strings inline.
That keeps the frontend easy to translate, test, and review.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from string import Formatter
from typing import Mapping

from chatbi.core.contracts import Locale


class TranslationKey(StrEnum):
    APP_TITLE = "app.title"
    CHAT_INPUT_PLACEHOLDER = "chat.input.placeholder"
    CHAT_SEND = "chat.send"
    CHAT_LOADING = "chat.loading"
    CHAT_EMPTY_STATE = "chat.empty_state"
    RESULT_TABLE_TITLE = "result.table.title"
    RESULT_CHART_TITLE = "result.chart.title"
    RESULT_ANALYTICS_TITLE = "result.analytics.title"
    RESULT_ANALYTICS_MODEL = "result.analytics.model"
    RESULT_ANALYTICS_ANOMALY = "result.analytics.anomaly"
    RESULT_ANALYTICS_FORECAST_POINTS = "result.analytics.forecast_points"
    RESULT_EVIDENCE_TITLE = "result.evidence.title"
    RESULT_SQL_EXPLAIN = "result.sql_explain"
    RESULT_CONFIDENCE = "result.confidence"
    TRACE_ID_LABEL = "trace.id.label"
    TRACE_COPY = "trace.copy"
    ERROR_VALIDATION_TITLE = "error.validation.title"
    ERROR_VALIDATION_MESSAGE = "error.validation.message"
    ERROR_SQL_GUARDRAIL_TITLE = "error.sql_guardrail.title"
    ERROR_SQL_GUARDRAIL_MESSAGE = "error.sql_guardrail.message"
    ERROR_INTERNAL_TITLE = "error.internal.title"
    ERROR_INTERNAL_MESSAGE = "error.internal.message"
    ERROR_RETRY = "error.retry"
    TASK_STATUS_QUEUED = "task.status.queued"
    TASK_STATUS_RUNNING = "task.status.running"
    TASK_STATUS_PARTIAL = "task.status.partial"
    TASK_STATUS_FAILED = "task.status.failed"
    TASK_STATUS_COMPLETED = "task.status.completed"
    TASK_STATUS_TITLE = "task.status.title"
    TASK_STATUS_INPUT_PLACEHOLDER = "task.status.input.placeholder"
    TASK_STATUS_LOAD = "task.status.load"
    TASK_STATUS_REFRESH = "task.status.refresh"
    TASK_STATUS_EMPTY = "task.status.empty"
    TASK_STATUS_RESULT_COUNT = "task.status.result_count"
    WARNING_PARTIAL_FAILURE = "warning.partial_failure"
    WARNING_RISK_REVIEW = "warning.risk_review"
    HISTORY_TITLE = "history.title"
    HISTORY_REPLAY = "history.replay"
    HISTORY_EMPTY = "history.empty"
    HISTORY_LOAD_MORE = "history.load_more"
    HISTORY_STATUS_SUCCEEDED = "history.status.succeeded"
    HISTORY_STATUS_FAILED = "history.status.failed"
    CATALOG_TITLE = "catalog.title"
    CATALOG_EMPTY = "catalog.empty"
    CATALOG_SEARCH_PLACEHOLDER = "catalog.search.placeholder"
    CATALOG_SELECTED_TITLE = "catalog.selected.title"
    CATALOG_SOURCE_TABLES = "catalog.source_tables"
    CATALOG_SEMANTIC_VERSION = "catalog.semantic_version"
    EVALUATION_TITLE = "evaluation.title"
    EVALUATION_RUN = "evaluation.run"
    EVALUATION_RUNNING = "evaluation.running"
    EVALUATION_EMPTY = "evaluation.empty"
    EVALUATION_GATE_NOT_RUN = "evaluation.gate.not_run"
    EVALUATION_GATE_PASSED = "evaluation.gate.passed"
    EVALUATION_GATE_FAILED = "evaluation.gate.failed"
    EVALUATION_SCORE = "evaluation.score"
    EVALUATION_CASES = "evaluation.cases"
    EVALUATION_FAILED_CASES = "evaluation.failed_cases"
    ERROR_SAFE_MESSAGE = "error.safe_message"
    ACCESSIBILITY_CHART_SUMMARY = "accessibility.chart_summary"


@dataclass(frozen=True, slots=True)
class I18nText:
    key: TranslationKey
    value: str


TRANSLATIONS: Mapping[Locale, Mapping[TranslationKey, str]] = {
    Locale.EN: {
        TranslationKey.APP_TITLE: "InsightOps AI",
        TranslationKey.CHAT_INPUT_PLACEHOLDER: "Ask a business question...",
        TranslationKey.CHAT_SEND: "Send",
        TranslationKey.CHAT_LOADING: "Analyzing your question...",
        TranslationKey.CHAT_EMPTY_STATE: "Start by asking a question about revenue, orders, users, or anomalies.",
        TranslationKey.RESULT_TABLE_TITLE: "Table",
        TranslationKey.RESULT_CHART_TITLE: "Chart",
        TranslationKey.RESULT_ANALYTICS_TITLE: "Analytics",
        TranslationKey.RESULT_ANALYTICS_MODEL: "Model: {model}",
        TranslationKey.RESULT_ANALYTICS_ANOMALY: "Anomaly level: {level}",
        TranslationKey.RESULT_ANALYTICS_FORECAST_POINTS: "Forecast points: {count}",
        TranslationKey.RESULT_EVIDENCE_TITLE: "Evidence",
        TranslationKey.RESULT_SQL_EXPLAIN: "SQL Explain",
        TranslationKey.RESULT_CONFIDENCE: "Confidence: {confidence}",
        TranslationKey.TRACE_ID_LABEL: "Trace ID: {trace_id}",
        TranslationKey.TRACE_COPY: "Copy trace ID",
        TranslationKey.ERROR_VALIDATION_TITLE: "Check your question",
        TranslationKey.ERROR_VALIDATION_MESSAGE: "The request is missing required information. Rephrase the question and try again.",
        TranslationKey.ERROR_SQL_GUARDRAIL_TITLE: "Query blocked for safety",
        TranslationKey.ERROR_SQL_GUARDRAIL_MESSAGE: "Only safe read-only analytics are allowed. Ask for a narrower business metric or time range.",
        TranslationKey.ERROR_INTERNAL_TITLE: "Something went wrong",
        TranslationKey.ERROR_INTERNAL_MESSAGE: "The system could not finish this request. Retry once, then use the trace ID if you ask for help.",
        TranslationKey.ERROR_RETRY: "Try again",
        TranslationKey.TASK_STATUS_QUEUED: "Queued",
        TranslationKey.TASK_STATUS_RUNNING: "Running",
        TranslationKey.TASK_STATUS_PARTIAL: "Partially completed",
        TranslationKey.TASK_STATUS_FAILED: "Failed",
        TranslationKey.TASK_STATUS_COMPLETED: "Completed",
        TranslationKey.TASK_STATUS_TITLE: "Task Status",
        TranslationKey.TASK_STATUS_INPUT_PLACEHOLDER: "Enter a task id...",
        TranslationKey.TASK_STATUS_LOAD: "Load status",
        TranslationKey.TASK_STATUS_REFRESH: "Refresh",
        TranslationKey.TASK_STATUS_EMPTY: "Enter a task id to check long-running work.",
        TranslationKey.TASK_STATUS_RESULT_COUNT: "{count} result fields",
        TranslationKey.WARNING_PARTIAL_FAILURE: "Some agents failed, so this answer may be incomplete.",
        TranslationKey.WARNING_RISK_REVIEW: "This result needs human review before business action.",
        TranslationKey.HISTORY_TITLE: "Query History",
        TranslationKey.HISTORY_REPLAY: "Replay",
        TranslationKey.HISTORY_EMPTY: "No query history yet.",
        TranslationKey.HISTORY_LOAD_MORE: "Load more",
        TranslationKey.HISTORY_STATUS_SUCCEEDED: "Succeeded",
        TranslationKey.HISTORY_STATUS_FAILED: "Failed",
        TranslationKey.CATALOG_TITLE: "Metric Catalog",
        TranslationKey.CATALOG_EMPTY: "No metrics are available.",
        TranslationKey.CATALOG_SEARCH_PLACEHOLDER: "Search metrics...",
        TranslationKey.CATALOG_SELECTED_TITLE: "Selected metric",
        TranslationKey.CATALOG_SOURCE_TABLES: "Source tables: {tables}",
        TranslationKey.CATALOG_SEMANTIC_VERSION: "Semantic version: {version}",
        TranslationKey.EVALUATION_TITLE: "Evaluation",
        TranslationKey.EVALUATION_RUN: "Run evaluation",
        TranslationKey.EVALUATION_RUNNING: "Running evaluation...",
        TranslationKey.EVALUATION_EMPTY: "Run an evaluation suite to inspect release quality.",
        TranslationKey.EVALUATION_GATE_NOT_RUN: "Not run",
        TranslationKey.EVALUATION_GATE_PASSED: "Release gate passed",
        TranslationKey.EVALUATION_GATE_FAILED: "Release gate failed",
        TranslationKey.EVALUATION_SCORE: "Overall score: {score}",
        TranslationKey.EVALUATION_CASES: "{passed}/{total} cases passed",
        TranslationKey.EVALUATION_FAILED_CASES: "{count} failed cases",
        TranslationKey.ERROR_SAFE_MESSAGE: "This request cannot be answered safely. Try narrowing the question.",
        TranslationKey.ACCESSIBILITY_CHART_SUMMARY: "{chart_type} chart with x field {x_field}.",
    },
    Locale.ZH_CN: {
        TranslationKey.APP_TITLE: "InsightOps AI",
        TranslationKey.CHAT_INPUT_PLACEHOLDER: "请输入一个业务问题...",
        TranslationKey.CHAT_SEND: "发送",
        TranslationKey.CHAT_LOADING: "正在分析你的问题...",
        TranslationKey.CHAT_EMPTY_STATE: "可以从收入、订单、用户或异常波动开始提问。",
        TranslationKey.RESULT_TABLE_TITLE: "表格",
        TranslationKey.RESULT_CHART_TITLE: "图表",
        TranslationKey.RESULT_ANALYTICS_TITLE: "分析",
        TranslationKey.RESULT_ANALYTICS_MODEL: "模型：{model}",
        TranslationKey.RESULT_ANALYTICS_ANOMALY: "异常等级：{level}",
        TranslationKey.RESULT_ANALYTICS_FORECAST_POINTS: "预测点数：{count}",
        TranslationKey.RESULT_EVIDENCE_TITLE: "证据",
        TranslationKey.RESULT_SQL_EXPLAIN: "SQL 解释",
        TranslationKey.RESULT_CONFIDENCE: "置信度：{confidence}",
        TranslationKey.TRACE_ID_LABEL: "追踪 ID：{trace_id}",
        TranslationKey.TRACE_COPY: "复制追踪 ID",
        TranslationKey.ERROR_VALIDATION_TITLE: "请检查你的问题",
        TranslationKey.ERROR_VALIDATION_MESSAGE: "这个请求缺少必要信息。请换一种更清楚的问法后重试。",
        TranslationKey.ERROR_SQL_GUARDRAIL_TITLE: "查询因安全策略被拦截",
        TranslationKey.ERROR_SQL_GUARDRAIL_MESSAGE: "系统只允许安全的只读分析。请缩小业务指标、时间范围或查询对象后重试。",
        TranslationKey.ERROR_INTERNAL_TITLE: "系统暂时无法完成请求",
        TranslationKey.ERROR_INTERNAL_MESSAGE: "这次请求没有成功完成。可以先重试一次，如果继续失败，请带上追踪 ID 排查。",
        TranslationKey.ERROR_RETRY: "重试",
        TranslationKey.TASK_STATUS_QUEUED: "已排队",
        TranslationKey.TASK_STATUS_RUNNING: "运行中",
        TranslationKey.TASK_STATUS_PARTIAL: "部分完成",
        TranslationKey.TASK_STATUS_FAILED: "失败",
        TranslationKey.TASK_STATUS_COMPLETED: "已完成",
        TranslationKey.TASK_STATUS_TITLE: "任务状态",
        TranslationKey.TASK_STATUS_INPUT_PLACEHOLDER: "请输入任务 ID...",
        TranslationKey.TASK_STATUS_LOAD: "加载状态",
        TranslationKey.TASK_STATUS_REFRESH: "刷新",
        TranslationKey.TASK_STATUS_EMPTY: "输入任务 ID 查看长任务状态。",
        TranslationKey.TASK_STATUS_RESULT_COUNT: "{count} 个结果字段",
        TranslationKey.WARNING_PARTIAL_FAILURE: "部分智能体执行失败，所以这个答案可能不完整。",
        TranslationKey.WARNING_RISK_REVIEW: "这个结果在用于业务决策前需要人工复核。",
        TranslationKey.HISTORY_TITLE: "查询历史",
        TranslationKey.HISTORY_REPLAY: "回放",
        TranslationKey.HISTORY_EMPTY: "还没有查询历史。",
        TranslationKey.HISTORY_LOAD_MORE: "加载更多",
        TranslationKey.HISTORY_STATUS_SUCCEEDED: "成功",
        TranslationKey.HISTORY_STATUS_FAILED: "失败",
        TranslationKey.CATALOG_TITLE: "指标目录",
        TranslationKey.CATALOG_EMPTY: "暂无可用指标。",
        TranslationKey.CATALOG_SEARCH_PLACEHOLDER: "搜索指标...",
        TranslationKey.CATALOG_SELECTED_TITLE: "已选指标",
        TranslationKey.CATALOG_SOURCE_TABLES: "来源表：{tables}",
        TranslationKey.CATALOG_SEMANTIC_VERSION: "语义版本：{version}",
        TranslationKey.EVALUATION_TITLE: "评估",
        TranslationKey.EVALUATION_RUN: "运行评估",
        TranslationKey.EVALUATION_RUNNING: "正在运行评估...",
        TranslationKey.EVALUATION_EMPTY: "运行评估套件来查看发布质量。",
        TranslationKey.EVALUATION_GATE_NOT_RUN: "未运行",
        TranslationKey.EVALUATION_GATE_PASSED: "发布门禁通过",
        TranslationKey.EVALUATION_GATE_FAILED: "发布门禁失败",
        TranslationKey.EVALUATION_SCORE: "总分：{score}",
        TranslationKey.EVALUATION_CASES: "{passed}/{total} 个用例通过",
        TranslationKey.EVALUATION_FAILED_CASES: "{count} 个失败用例",
        TranslationKey.ERROR_SAFE_MESSAGE: "这个请求无法安全回答，请尝试缩小问题范围。",
        TranslationKey.ACCESSIBILITY_CHART_SUMMARY: "{chart_type} 图，横轴字段是 {x_field}。",
    },
}


def translate(
    key: TranslationKey,
    locale: Locale,
    variables: Mapping[str, object] | None = None,
) -> str:
    """Return localized UI text and fill optional template variables."""

    template = _template_for(key=key, locale=locale)
    if variables is None:
        return template
    _ensure_template_variables(template=template, variables=variables)
    return template.format(**variables)


def translated_texts(locale: Locale) -> tuple[I18nText, ...]:
    """Return all texts for a locale, useful for page bootstrapping."""

    return tuple(
        I18nText(key=key, value=value)
        for key, value in TRANSLATIONS[locale].items()
    )


def _template_for(key: TranslationKey, locale: Locale) -> str:
    locale_dictionary = TRANSLATIONS.get(locale)
    if locale_dictionary is None:
        return TRANSLATIONS[Locale.EN][key]
    return locale_dictionary.get(key, TRANSLATIONS[Locale.EN][key])


def _ensure_template_variables(
    template: str,
    variables: Mapping[str, object],
) -> None:
    required = {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name is not None
    }
    missing = required - set(variables)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing i18n template variables: {missing_list}")
