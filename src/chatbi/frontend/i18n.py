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
    WARNING_PARTIAL_FAILURE = "warning.partial_failure"
    WARNING_RISK_REVIEW = "warning.risk_review"
    HISTORY_TITLE = "history.title"
    HISTORY_REPLAY = "history.replay"
    CATALOG_TITLE = "catalog.title"
    EVALUATION_TITLE = "evaluation.title"
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
        TranslationKey.WARNING_PARTIAL_FAILURE: "Some agents failed, so this answer may be incomplete.",
        TranslationKey.WARNING_RISK_REVIEW: "This result needs human review before business action.",
        TranslationKey.HISTORY_TITLE: "Query History",
        TranslationKey.HISTORY_REPLAY: "Replay",
        TranslationKey.CATALOG_TITLE: "Metric Catalog",
        TranslationKey.EVALUATION_TITLE: "Evaluation",
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
        TranslationKey.WARNING_PARTIAL_FAILURE: "部分智能体执行失败，所以这个答案可能不完整。",
        TranslationKey.WARNING_RISK_REVIEW: "这个结果在用于业务决策前需要人工复核。",
        TranslationKey.HISTORY_TITLE: "查询历史",
        TranslationKey.HISTORY_REPLAY: "回放",
        TranslationKey.CATALOG_TITLE: "指标目录",
        TranslationKey.EVALUATION_TITLE: "评估",
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
