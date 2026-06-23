"""Metric Catalog page state for the Frontend ChatBI slice.

The catalog is metadata, not query output. It helps users understand what
business metrics are available before they ask questions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol, cast

from chatbi.frontend.api_client import FrontendUserContext, MetricCatalogViewModel


@dataclass(frozen=True, slots=True)
class MetricDefinitionViewModel:
    name: str
    sql_definition: str
    source_tables: tuple[str, ...]
    semantic_version: str

    @property
    def search_text(self) -> str:
        return " ".join(
            (
                self.name,
                self.sql_definition,
                " ".join(self.source_tables),
                self.semantic_version,
            )
        ).lower()


@dataclass(frozen=True, slots=True)
class CatalogPageState:
    context: FrontendUserContext
    metrics: tuple[MetricDefinitionViewModel, ...] = ()
    search_query: str = ""
    selected_metric_name: str | None = None
    is_loading: bool = False
    error_message: str | None = None

    @property
    def filtered_metrics(self) -> tuple[MetricDefinitionViewModel, ...]:
        normalized_query = self.search_query.strip().lower()
        if not normalized_query:
            return self.metrics
        return tuple(
            metric
            for metric in self.metrics
            if normalized_query in metric.search_text
        )

    @property
    def selected_metric(self) -> MetricDefinitionViewModel | None:
        if self.selected_metric_name is None:
            return None
        for metric in self.metrics:
            if metric.name == self.selected_metric_name:
                return metric
        return None


class CatalogApiPort(Protocol):
    def load_metric_catalog(self, context: FrontendUserContext) -> MetricCatalogViewModel:
        """Load metric definitions from the Backend API."""
        ...


class CatalogPageStore:
    """Small in-memory store for the Metric Catalog page."""

    def __init__(
        self,
        context: FrontendUserContext,
        api_client: CatalogApiPort,
    ) -> None:
        self._api_client = api_client
        self._state = CatalogPageState(context=context)

    @property
    def state(self) -> CatalogPageState:
        return self._state

    def load_catalog(self) -> CatalogPageState:
        self._state = replace(
            self._state,
            is_loading=True,
            error_message=None,
        )

        try:
            catalog = self._api_client.load_metric_catalog(context=self._state.context)
        except ValueError as exc:
            self._state = replace(
                self._state,
                is_loading=False,
                error_message=str(exc),
            )
            return self._state

        metrics = tuple(_metric_definition(raw_metric) for raw_metric in catalog.metrics)
        selected_metric_name = self._state.selected_metric_name
        if selected_metric_name not in {metric.name for metric in metrics}:
            selected_metric_name = metrics[0].name if metrics else None

        self._state = replace(
            self._state,
            metrics=metrics,
            selected_metric_name=selected_metric_name,
            is_loading=False,
            error_message=None,
        )
        return self._state

    def set_search_query(self, search_query: str) -> CatalogPageState:
        self._state = replace(
            self._state,
            search_query=search_query.strip(),
            error_message=None,
        )
        return self._state

    def select_metric(self, metric_name: str) -> CatalogPageState:
        normalized_name = metric_name.strip()
        if normalized_name not in {metric.name for metric in self._state.metrics}:
            self._state = replace(
                self._state,
                selected_metric_name=None,
                error_message="Metric was not found.",
            )
            return self._state

        self._state = replace(
            self._state,
            selected_metric_name=normalized_name,
            error_message=None,
        )
        return self._state


def _metric_definition(raw_metric: Mapping[str, Any]) -> MetricDefinitionViewModel:
    return MetricDefinitionViewModel(
        name=_string(raw_metric.get("name"), field_name="name"),
        sql_definition=_string(
            raw_metric.get("sql_definition"),
            field_name="sql_definition",
        ),
        source_tables=tuple(
            _string(source_table, field_name="source_tables")
            for source_table in _sequence(
                raw_metric.get("source_tables"),
                field_name="source_tables",
            )
        ),
        semantic_version=_string(
            raw_metric.get("semantic_version"),
            field_name="semantic_version",
        ),
    )


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
