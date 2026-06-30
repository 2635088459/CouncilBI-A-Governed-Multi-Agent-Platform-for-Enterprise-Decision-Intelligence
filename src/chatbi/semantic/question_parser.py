"""Deterministic question parser for the first NL2SQL slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
import re

from chatbi.semantic.catalog import FieldDefinition, MetricDefinition, MetricResolution, SemanticCatalog


class TimeGrain(StrEnum):
    DAY = "day"
    MONTH = "month"


@dataclass(frozen=True, slots=True)
class TimeRange:
    start_date: date
    end_date: date
    source: str


@dataclass(frozen=True, slots=True)
class ParsedQuestion:
    metric: MetricDefinition | None
    time_range: TimeRange
    original_question: str
    time_grain: TimeGrain = TimeGrain.DAY
    metric_candidates: tuple[MetricDefinition, ...] = ()
    requested_field: FieldDefinition | None = None

    @property
    def needs_clarification(self) -> bool:
        return len(self.metric_candidates) > 1


class QuestionParser:
    """Extract the metric and time range from a supported question."""

    def __init__(self, catalog: SemanticCatalog, today: date | None = None) -> None:
        self._catalog = catalog
        self._today = today or date.today()

    def parse(self, question: str) -> ParsedQuestion:
        metric_resolution = self._resolve_metric(question)
        return ParsedQuestion(
            metric=metric_resolution.metric,
            time_range=self._resolve_time_range(question),
            original_question=question,
            time_grain=self._resolve_time_grain(question),
            metric_candidates=metric_resolution.candidates,
            requested_field=self._resolve_field(question),
        )

    def _resolve_metric(self, question: str) -> MetricResolution:
        for term in self._catalog.known_aliases():
            if term in self._normalize(question):
                return self._catalog.resolve_metric_candidates(term)
        return MetricResolution(metric=None)

    def _resolve_field(self, question: str) -> FieldDefinition | None:
        normalized_question = self._normalize(question)
        for term in self._catalog.known_field_aliases():
            if term in normalized_question:
                return self._catalog.resolve_field(term)
        return None

    def _resolve_time_range(self, question: str) -> TimeRange:
        normalized_question = self._normalize(question)
        year = self._resolve_explicit_year(normalized_question)
        if year is not None:
            return TimeRange(
                start_date=date(year, 1, 1),
                end_date=date(year, 12, 31),
                source=f"explicit_year_{year}",
            )
        if "last 30 days" in normalized_question:
            return self._last_n_days(days=30, source="explicit_last_30_days")
        return self._last_n_days(days=30, source="default_last_30_days")

    def _resolve_time_grain(self, question: str) -> TimeGrain:
        normalized_question = self._normalize(question)
        if self._contains_any(normalized_question, ("monthly", "by month", "per month")):
            return TimeGrain.MONTH
        return TimeGrain.DAY

    def _resolve_explicit_year(self, normalized_question: str) -> int | None:
        year_match = re.search(r"\b(20\d{2})\b", normalized_question)
        if year_match is None:
            return None
        return int(year_match.group(1))

    def _last_n_days(self, days: int, source: str) -> TimeRange:
        return TimeRange(
            start_date=self._today - timedelta(days=days),
            end_date=self._today,
            source=source,
        )

    def _normalize(self, text: str) -> str:
        return " ".join(text.strip().lower().split())

    def _contains_any(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)
