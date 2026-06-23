"""Frontend view models for rendering ChatBI API responses.

The backend returns business data. The frontend needs screen-ready blocks.
This module is the adapter between those two worlds: it turns one API answer
into small cards that the UI can render independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, cast

from chatbi.core.contracts import ChartType, ErrorCode


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ResultBlockType(StrEnum):
    TABLE = "table"
    CHART = "chart"
    ANALYTICS = "analytics"
    EVIDENCE = "evidence"
    SQL_EXPLAIN = "sql_explain"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class MessageBubbleViewModel:
    role: MessageRole
    text: str
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class WarningBannerViewModel:
    code: str
    message: str
    is_partial_failure: bool


@dataclass(frozen=True, slots=True)
class TableCardViewModel:
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ChartCardViewModel:
    chart_type: ChartType
    x_field: str
    y_fields: tuple[str, ...]
    title: str


@dataclass(frozen=True, slots=True)
class EvidenceCardViewModel:
    source_id: str
    title: str
    citation_anchor: str
    snippet: str


@dataclass(frozen=True, slots=True)
class AnalyticsCardViewModel:
    model_used: str
    anomaly_level: str
    forecast_points: int
    fact: str
    judgment: str
    uncertainty: str


@dataclass(frozen=True, slots=True)
class SqlExplainCardViewModel:
    sql_text: str
    explanation: str


@dataclass(frozen=True, slots=True)
class QueryResultViewModel:
    trace_id: str
    answer: MessageBubbleViewModel
    warnings: tuple[WarningBannerViewModel, ...]
    table: TableCardViewModel | None
    chart: ChartCardViewModel | None
    analytics: AnalyticsCardViewModel | None
    evidence: tuple[EvidenceCardViewModel, ...]
    sql_explain: SqlExplainCardViewModel
    confidence: float

    @property
    def blocks(self) -> tuple[ResultBlockType, ...]:
        """Return the render order required by the frontend spec."""

        ordered: list[ResultBlockType] = []
        if self.warnings:
            ordered.append(ResultBlockType.WARNING)
        if self.table is not None:
            ordered.append(ResultBlockType.TABLE)
        if self.chart is not None:
            ordered.append(ResultBlockType.CHART)
        if self.analytics is not None:
            ordered.append(ResultBlockType.ANALYTICS)
        if self.evidence:
            ordered.append(ResultBlockType.EVIDENCE)
        ordered.append(ResultBlockType.SQL_EXPLAIN)
        return tuple(ordered)


def build_query_result_view_model(api_envelope: Mapping[str, Any]) -> QueryResultViewModel:
    """Convert a successful Backend API envelope into screen-ready cards."""

    data = _mapping(api_envelope.get("data"), field_name="data")
    trace_id = _string(api_envelope.get("trace_id"), field_name="trace_id")
    answer_text = _string(data.get("answer_text"), field_name="answer_text")
    sql_text = _string(data.get("sql_text"), field_name="sql_text")

    return QueryResultViewModel(
        trace_id=trace_id,
        answer=MessageBubbleViewModel(
            role=MessageRole.ASSISTANT,
            text=answer_text,
            trace_id=trace_id,
        ),
        warnings=_warning_banners(api_envelope.get("warnings", ())),
        table=_table_card(data.get("table_result")),
        chart=_chart_card(
            raw_chart_spec=data.get("chart_spec"),
            table_result=data.get("table_result"),
        ),
        analytics=_analytics_card(data.get("analytics_result")),
        evidence=_evidence_cards(data.get("evidence_list", ())),
        sql_explain=SqlExplainCardViewModel(
            sql_text=sql_text,
            explanation="Generated SQL used by the governed query pipeline.",
        ),
        confidence=float(data.get("confidence", 1.0)),
    )


def _warning_banners(raw_warnings: object) -> tuple[WarningBannerViewModel, ...]:
    warnings = _sequence(raw_warnings, field_name="warnings")
    banners: list[WarningBannerViewModel] = []
    for warning in warnings:
        warning_data = _mapping(warning, field_name="warning")
        code = _string(warning_data.get("code"), field_name="warning.code")
        banners.append(
            WarningBannerViewModel(
                code=code,
                message=_string(warning_data.get("message"), field_name="warning.message"),
                is_partial_failure=code == ErrorCode.AGENT_PARTIAL_FAILURE,
            )
        )
    return tuple(banners)


def _table_card(raw_table: object) -> TableCardViewModel | None:
    if raw_table is None:
        return None
    table = _mapping(raw_table, field_name="table_result")
    columns = tuple(
        _string(column, field_name="table_result.columns")
        for column in _sequence(table.get("columns", ()), field_name="table_result.columns")
    )
    rows = tuple(
        _mapping(row, field_name="table_result.rows")
        for row in _sequence(table.get("rows", ()), field_name="table_result.rows")
    )
    return TableCardViewModel(columns=columns, rows=rows)


def _chart_card(raw_chart_spec: object, table_result: object) -> ChartCardViewModel | None:
    if raw_chart_spec is None:
        return _default_time_series_chart(table_result)

    chart_spec = _mapping(raw_chart_spec, field_name="chart_spec")
    return ChartCardViewModel(
        chart_type=ChartType(_string(chart_spec.get("chart_type"), field_name="chart_spec.chart_type")),
        x_field=_string(chart_spec.get("x_field"), field_name="chart_spec.x_field"),
        y_fields=tuple(
            _string(field, field_name="chart_spec.y_fields")
            for field in _sequence(chart_spec.get("y_fields", ()), field_name="chart_spec.y_fields")
        ),
        title=str(chart_spec.get("title") or "Chart"),
    )


def _default_time_series_chart(table_result: object) -> ChartCardViewModel | None:
    table = _table_card(table_result)
    if table is None or len(table.columns) < 2:
        return None

    x_field = table.columns[0]
    if not _looks_like_time_field(x_field):
        return None

    return ChartCardViewModel(
        chart_type=ChartType.LINE,
        x_field=x_field,
        y_fields=table.columns[1:],
        title="Time series",
    )


def _evidence_cards(raw_evidence: object) -> tuple[EvidenceCardViewModel, ...]:
    evidence_items = _sequence(raw_evidence, field_name="evidence_list")
    cards: list[EvidenceCardViewModel] = []
    for evidence in evidence_items:
        evidence_data = _mapping(evidence, field_name="evidence")
        cards.append(
            EvidenceCardViewModel(
                source_id=_string(evidence_data.get("source_id"), field_name="evidence.source_id"),
                title=_string(evidence_data.get("title"), field_name="evidence.title"),
                citation_anchor=_string(
                    evidence_data.get("citation_anchor"),
                    field_name="evidence.citation_anchor",
                ),
                snippet=_string(evidence_data.get("snippet"), field_name="evidence.snippet"),
            )
        )
    return tuple(cards)


def _analytics_card(raw_analytics: object) -> AnalyticsCardViewModel | None:
    if raw_analytics is None:
        return None

    analytics = _mapping(raw_analytics, field_name="analytics_result")
    forecast = _mapping(
        analytics.get("forecast_result"),
        field_name="analytics_result.forecast_result",
    )
    anomaly = _mapping(
        analytics.get("anomaly_result"),
        field_name="analytics_result.anomaly_result",
    )
    narrative = _mapping(
        analytics.get("narrative"),
        field_name="analytics_result.narrative",
    )

    return AnalyticsCardViewModel(
        model_used=_string(forecast.get("model_used"), field_name="forecast_result.model_used"),
        anomaly_level=_string(anomaly.get("anomaly_level"), field_name="anomaly_result.anomaly_level"),
        forecast_points=len(
            _sequence(
                forecast.get("forecast_series", ()),
                field_name="forecast_result.forecast_series",
            )
        ),
        fact=_string(narrative.get("fact"), field_name="narrative.fact"),
        judgment=_string(narrative.get("judgment"), field_name="narrative.judgment"),
        uncertainty=_string(narrative.get("uncertainty"), field_name="narrative.uncertainty"),
    )


def _looks_like_time_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return "date" in normalized or "time" in normalized or normalized.endswith("_month")


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return cast(Mapping[str, Any], value)


def _sequence(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, tuple):
        return cast(tuple[object, ...], value)
    if isinstance(value, list):
        return tuple(cast(list[object], value))
    raise ValueError(f"{field_name} must be a list")


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value
