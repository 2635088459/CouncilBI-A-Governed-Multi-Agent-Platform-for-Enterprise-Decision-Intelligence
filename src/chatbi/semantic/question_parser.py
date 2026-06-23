"""Deterministic question parser for the first NL2SQL slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from chatbi.semantic.catalog import FieldDefinition, MetricDefinition, MetricResolution, SemanticCatalog


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
        if "last 30 days" in normalized_question:
            return self._last_n_days(days=30, source="explicit_last_30_days")
        return self._last_n_days(days=30, source="default_last_30_days")

    def _last_n_days(self, days: int, source: str) -> TimeRange:
        return TimeRange(
            start_date=self._today - timedelta(days=days),
            end_date=self._today,
            source=source,
        )

    def _normalize(self, text: str) -> str:
        return " ".join(text.strip().lower().split())
