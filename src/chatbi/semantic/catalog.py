"""Semantic metric catalog for governed NL2SQL."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SensitivityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MetricStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    description: str
    table_name: str
    sql_expression: str
    semantic_version: str
    synonyms: tuple[str, ...] = ()
    owner: str = "analytics"
    status: MetricStatus = MetricStatus.ACTIVE

    def __post_init__(self) -> None:
        required_values = {
            "name": self.name,
            "description": self.description,
            "table_name": self.table_name,
            "sql_expression": self.sql_expression,
            "semantic_version": self.semantic_version,
            "owner": self.owner,
        }
        for field_name, value in required_values.items():
            if not value.strip():
                raise ValueError(f"{field_name} is required")

    @property
    def metric_id(self) -> str:
        return self.name

    @property
    def formula(self) -> str:
        return self.sql_expression

    @property
    def semantic_version_id(self) -> str:
        return self.semantic_version


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    name: str
    description: str
    table_name: str
    sql_expression: str
    sensitivity: SensitivityLevel
    semantic_version: str
    synonyms: tuple[str, ...] = ()

    @property
    def is_high_sensitivity(self) -> bool:
        return self.sensitivity is SensitivityLevel.HIGH

    @property
    def field_id(self) -> str:
        return self.name

    @property
    def semantic_version_id(self) -> str:
        return self.semantic_version


@dataclass(frozen=True, slots=True)
class MetricResolution:
    metric: MetricDefinition | None
    candidates: tuple[MetricDefinition, ...] = ()

    @property
    def is_ambiguous(self) -> bool:
        return len(self.candidates) > 1


class SemanticCatalog:
    """Resolve business terms to canonical metric definitions."""

    def __init__(
        self,
        metrics: tuple[MetricDefinition, ...],
        fields: tuple[FieldDefinition, ...] = (),
    ) -> None:
        self._metrics = metrics
        self._fields = fields
        self._metrics_by_name = {metric.name: metric for metric in metrics}
        self._fields_by_name = {field.name: field for field in fields}
        self._canonical_metric_by_alias = self._build_metric_alias_index(metrics)
        self._canonical_field_by_alias = self._build_field_alias_index(fields)

    def get_metric(self, canonical_name: str) -> MetricDefinition | None:
        return self._metrics_by_name.get(canonical_name)

    def get_field(self, canonical_name: str) -> FieldDefinition | None:
        return self._fields_by_name.get(canonical_name)

    def known_aliases(self) -> tuple[str, ...]:
        return tuple(self._canonical_metric_by_alias.keys())

    def known_field_aliases(self) -> tuple[str, ...]:
        return tuple(self._canonical_field_by_alias.keys())

    def resolve_metric(self, term: str) -> MetricDefinition | None:
        resolution = self.resolve_metric_candidates(term)
        return resolution.metric

    def resolve_field(self, term: str) -> FieldDefinition | None:
        normalized_term = self._normalize(term)
        canonical_name = self._canonical_field_by_alias.get(normalized_term)
        if canonical_name is None:
            return None
        return self._fields_by_name[canonical_name]

    def resolve_metric_candidates(self, term: str) -> MetricResolution:
        normalized_term = self._normalize(term)
        candidate_names = self._canonical_metric_by_alias.get(normalized_term, ())
        candidates = tuple(self._metrics_by_name[name] for name in candidate_names)
        if len(candidates) == 1:
            return MetricResolution(metric=candidates[0], candidates=candidates)
        return MetricResolution(metric=None, candidates=candidates)

    def with_updated_metric(self, updated_metric: MetricDefinition) -> SemanticCatalog:
        existing_metric = self.get_metric(updated_metric.name)
        if (
            existing_metric is not None
            and self._metric_definition_changed(existing_metric, updated_metric)
            and existing_metric.semantic_version == updated_metric.semantic_version
        ):
            raise ValueError("metric definition changes must increment semantic_version")

        metrics = tuple(
            updated_metric if metric.name == updated_metric.name else metric
            for metric in self._metrics
        )
        if existing_metric is None:
            metrics = (*metrics, updated_metric)
        return SemanticCatalog(metrics=metrics, fields=self._fields)

    def _build_metric_alias_index(self, metrics: tuple[MetricDefinition, ...]) -> dict[str, tuple[str, ...]]:
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

    def _build_field_alias_index(self, fields: tuple[FieldDefinition, ...]) -> dict[str, str]:
        alias_index: dict[str, str] = {}
        for field in fields:
            aliases = (field.name, *field.synonyms)
            for alias in aliases:
                alias_index[self._normalize(alias)] = field.name
        return alias_index

    def _normalize(self, term: str) -> str:
        return " ".join(term.strip().lower().split())

    def _metric_definition_changed(
        self,
        existing_metric: MetricDefinition,
        updated_metric: MetricDefinition,
    ) -> bool:
        return (
            existing_metric.description != updated_metric.description
            or existing_metric.table_name != updated_metric.table_name
            or existing_metric.sql_expression != updated_metric.sql_expression
            or existing_metric.synonyms != updated_metric.synonyms
            or existing_metric.owner != updated_metric.owner
            or existing_metric.status != updated_metric.status
        )


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
    user_id = FieldDefinition(
        name="user_id",
        description="Direct user identifier attached to an order.",
        table_name="orders",
        sql_expression="orders.user_id",
        sensitivity=SensitivityLevel.HIGH,
        semantic_version="sem_v1",
        synonyms=(
            "user id",
            "customer id",
            "buyer id",
        ),
    )
    return SemanticCatalog(metrics=(revenue,), fields=(user_id,))
