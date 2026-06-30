"""Analytics page state for direct v2 metric analysis.

The API client knows the HTTP routes. This store keeps UI-friendly state:
which metric request is selected, whether sync analysis or async enqueue is in
progress, and the latest result or task returned by the backend.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from chatbi.frontend.api_client import (
    FrontendAnalyticsRequest,
    FrontendAnalyticsResultViewModel,
    FrontendUserContext,
)
from chatbi.frontend.task_status_state import TaskStatusViewModel


@dataclass(frozen=True, slots=True)
class AnalyticsPageState:
    context: FrontendUserContext
    request: FrontendAnalyticsRequest | None = None
    latest_result: FrontendAnalyticsResultViewModel | None = None
    latest_task: TaskStatusViewModel | None = None
    is_loading: bool = False
    error_message: str | None = None

    @property
    def has_result(self) -> bool:
        return self.latest_result is not None

    @property
    def has_task(self) -> bool:
        return self.latest_task is not None


class AnalyticsApiPort(Protocol):
    def analyze_metric(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> FrontendAnalyticsResultViewModel:
        """Run one synchronous analytics v2 request."""
        ...

    def enqueue_analytics(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> TaskStatusViewModel:
        """Create one asynchronous analytics v2 task."""
        ...

    def load_analytics_result(
        self,
        context: FrontendUserContext,
        trace_id: str,
    ) -> FrontendAnalyticsResultViewModel:
        """Load one persisted analytics v2 result by trace id."""
        ...


class AnalyticsPageStore:
    """Small in-memory store for direct analytics workflows."""

    def __init__(
        self,
        context: FrontendUserContext,
        api_client: AnalyticsApiPort,
    ) -> None:
        self._api_client = api_client
        self._state = AnalyticsPageState(context=context)

    @property
    def state(self) -> AnalyticsPageState:
        return self._state

    def set_request(self, request: FrontendAnalyticsRequest) -> AnalyticsPageState:
        _validate_request(request)
        self._state = replace(
            self._state,
            request=request,
            error_message=None,
        )
        return self._state

    def run_current_request(self) -> AnalyticsPageState:
        if self._state.request is None:
            self._state = replace(
                self._state,
                error_message="Analytics request is required.",
            )
            return self._state
        return self.run_request(self._state.request)

    def run_request(self, request: FrontendAnalyticsRequest) -> AnalyticsPageState:
        _validate_request(request)
        self._state = replace(
            self._state,
            request=request,
            is_loading=True,
            error_message=None,
        )

        try:
            result = self._api_client.analyze_metric(
                context=self._state.context,
                request=request,
            )
        except ValueError as exc:
            self._state = replace(
                self._state,
                is_loading=False,
                error_message=str(exc),
            )
            return self._state

        self._state = replace(
            self._state,
            latest_result=result,
            latest_task=None,
            is_loading=False,
            error_message=None,
        )
        return self._state

    def enqueue_current_request(self) -> AnalyticsPageState:
        if self._state.request is None:
            self._state = replace(
                self._state,
                error_message="Analytics request is required.",
            )
            return self._state
        return self.enqueue_request(self._state.request)

    def enqueue_request(self, request: FrontendAnalyticsRequest) -> AnalyticsPageState:
        _validate_request(request)
        self._state = replace(
            self._state,
            request=request,
            is_loading=True,
            error_message=None,
        )

        try:
            task = self._api_client.enqueue_analytics(
                context=self._state.context,
                request=request,
            )
        except ValueError as exc:
            self._state = replace(
                self._state,
                is_loading=False,
                error_message=str(exc),
            )
            return self._state

        self._state = replace(
            self._state,
            latest_task=task,
            is_loading=False,
            error_message=None,
        )
        return self._state

    def load_result(self, trace_id: str) -> AnalyticsPageState:
        normalized_trace_id = _normalize_required(trace_id, "Trace id is required.")
        self._state = replace(
            self._state,
            is_loading=True,
            error_message=None,
        )

        try:
            result = self._api_client.load_analytics_result(
                context=self._state.context,
                trace_id=normalized_trace_id,
            )
        except ValueError as exc:
            self._state = replace(
                self._state,
                is_loading=False,
                error_message=str(exc),
            )
            return self._state

        self._state = replace(
            self._state,
            latest_result=result,
            is_loading=False,
            error_message=None,
        )
        return self._state


def _validate_request(request: FrontendAnalyticsRequest) -> None:
    _normalize_required(request.trace_id, "Trace id is required.")
    _normalize_required(request.metric_id, "Metric id is required.")
    _normalize_required(request.semantic_version_id, "Semantic version id is required.")
    _normalize_required(request.time_column, "Time column is required.")
    _normalize_required(request.value_column, "Value column is required.")
    if request.grain not in {"day", "week", "month"}:
        raise ValueError("Analytics grain must be day, week, or month.")
    if not request.rows:
        raise ValueError("Analytics rows are required.")
    if request.horizon <= 0:
        raise ValueError("Analytics horizon must be positive.")


def _normalize_required(value: str, message: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(message)
    return normalized
