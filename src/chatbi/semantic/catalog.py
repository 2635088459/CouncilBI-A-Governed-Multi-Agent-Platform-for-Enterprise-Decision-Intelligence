"""Semantic metric catalog for governed NL2SQL."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    description: str
    table_name: str
    sql_expression: str
    semantic_version: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetricResolution:
    metric: MetricDefinition | None
    candidates: tuple[MetricDefinition, ...] = ()

    @property
    def is_ambiguous(self) -> bool:
        return len(self.candidates) > 1


class SemanticCatalog:
    """Resolve business terms to canonical metric definitions."""

    def __init__(self, metrics: tuple[MetricDefinition, ...]) -> None:
        self._metrics_by_name = {metric.name: metric for metric in metrics}
        self._canonical_by_alias = self._build_alias_index(metrics)

    def get_metric(self, canonical_name: str) -> MetricDefinition | None:
        return self._metrics_by_name.get(canonical_name)

    def known_aliases(self) -> tuple[str, ...]:
        return tuple(self._canonical_by_alias.keys())

    def resolve_metric(self, term: str) -> MetricDefinition | None:
        resolution = self.resolve_metric_candidates(term)
        return resolution.metric

    def resolve_metric_candidates(self, term: str) -> MetricResolution:
        normalized_term = self._normalize(term)
        candidate_names = self._canonical_by_alias.get(normalized_term, ())
        candidates = tuple(self._metrics_by_name[name] for name in candidate_names)
        if len(candidates) == 1:
            return MetricResolution(metric=candidates[0], candidates=candidates)
        return MetricResolution(metric=None, candidates=candidates)

    def _build_alias_index(self, metrics: tuple[MetricDefinition, ...]) -> dict[str, tuple[str, ...]]:
        alias_index: dict[str, list[str]] = {}
        for metric in metrics:
            aliases = (metric.name, *metric.synonyms)
            for alias in aliases:
                normalized_alias = self._normalize(alias)
                alias_index.setdefault(normalized_alias, []).append(metric.name)
        return {
            alias: tuple(metric_names)
            for alias, metric_names in alias_index.items()
        }

    def _normalize(self, term: str) -> str:
        return " ".join(term.strip().lower().split())


def build_default_catalog() -> SemanticCatalog:
    revenue = MetricDefinition(
        name="revenue",
        description="Total paid order amount.",
        table_name="orders",
        sql_expression="SUM(orders.order_amount) WHERE orders.status = 'paid'",
        semantic_version="sem_v1",
        synonyms=(
            "sales amount",
            "paid order amount",
            "total sales",
        ),
    )
    return SemanticCatalog(metrics=(revenue,))
