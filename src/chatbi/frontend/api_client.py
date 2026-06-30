"""Frontend-facing client for the Backend API.

This is not an agent client and not a database client. It only knows Backend
API routes, which keeps the frontend boundary clean and matches spec/07.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping, Protocol, cast

from chatbi.core.contracts import Locale, UserRole, new_trace_id
from chatbi.frontend.observability import FrontendLogger
from chatbi.frontend.task_status_state import (
    TaskStatusViewModel,
    build_task_status_view_model,
)
from chatbi.frontend.view_models import QueryResultViewModel, build_query_result_view_model


class JsonTransport(Protocol):
    def post_json(
        self,
        path: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        """Send JSON POST and return a decoded JSON object."""
        ...

    def get_json(
        self,
        path: str,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        """Send GET and return a decoded JSON object."""
        ...


@dataclass(frozen=True, slots=True)
class FrontendUserContext:
    user_id: str
    session_id: str
    locale: Locale
    role: UserRole
    bearer_token: str


@dataclass(frozen=True, slots=True)
class HistoryListViewModel:
    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    page_size: int


@dataclass(frozen=True, slots=True)
class MetricCatalogViewModel:
    metrics: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class FrontendApiError:
    code: str
    message: str
    retryable: bool


class FrontendApiException(ValueError):
    """Raised when the backend returns an error envelope."""

    def __init__(
        self,
        error: FrontendApiError,
        trace_id: str | None,
        request_id: str,
    ) -> None:
        super().__init__(error.message)
        self.error = error
        self.trace_id = trace_id
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class FrontendApiEnvelope:
    data: Mapping[str, Any] | None
    warnings: tuple[Mapping[str, Any], ...]
    error: FrontendApiError | None
    trace_id: str | None
    request_id: str

    def as_mapping(self) -> Mapping[str, Any]:
        """Return the normalized shape expected by existing view-model builders."""

        return {
            "data": self.data,
            "warnings": self.warnings,
            "error": None
            if self.error is None
            else {
                "code": self.error.code,
                "message": self.error.message,
                "retryable": self.error.retryable,
            },
            "trace_id": self.trace_id,
            "request_id": self.request_id,
        }


@dataclass(frozen=True, slots=True)
class EvaluationRunViewModel:
    eval_run_id: str
    eval_suite_id: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    overall_score: float
    average_confidence: float
    metric_breakdown: Mapping[str, float]
    failed_cases_detail: tuple[Mapping[str, Any], ...]
    release_gate_passed: bool


@dataclass(frozen=True, slots=True)
class FrontendAnalyticsRequest:
    trace_id: str
    metric_id: str
    semantic_version_id: str
    time_column: str
    value_column: str
    grain: str
    rows: tuple[Mapping[str, Any], ...]
    horizon: int = 3
    anomaly_z_threshold: float = 3.0

    def as_body(self) -> Mapping[str, Any]:
        return {
            "trace_id": self.trace_id,
            "metric_id": self.metric_id,
            "semantic_version_id": self.semantic_version_id,
            "time_column": self.time_column,
            "value_column": self.value_column,
            "grain": self.grain,
            "rows": self.rows,
            "analysis_options": {
                "horizon": self.horizon,
                "anomaly_z_threshold": self.anomaly_z_threshold,
            },
        }


@dataclass(frozen=True, slots=True)
class FrontendAnalyticsResultViewModel:
    trace_id: str
    metric_id: str
    semantic_version_id: str
    method: str
    model_version: str
    anomaly_points: tuple[Mapping[str, Any], ...]
    forecast_points: tuple[Mapping[str, Any], ...]
    quality_warnings: tuple[str, ...]
    explanation: str


class FrontendApiClient:
    def __init__(
        self,
        transport: JsonTransport,
        logger: FrontendLogger | None = None,
    ) -> None:
        self._transport = transport
        self._logger = logger or FrontendLogger()

    @property
    def logger(self) -> FrontendLogger:
        return self._logger

    def submit_question(
        self,
        context: FrontendUserContext,
        question: str,
        idempotency_key: str | None = None,
    ) -> QueryResultViewModel:
        """POST a natural-language question and return render-ready cards."""

        trace_id = new_trace_id()
        headers = _headers(
            context=context,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )
        self._logger.record_query_submitted(
            request_id=headers["X-Request-Id"],
            session_id=context.session_id,
            trace_id=trace_id,
            user_id=context.user_id,
        )
        start_time = perf_counter()
        envelope = self._transport.post_json(
            path="/api/v1/chat/query",
            headers=headers,
            body={
                "user_id": context.user_id,
                "session_id": context.session_id,
                "question": question,
                "locale": context.locale.value,
                "role": context.role.value,
            },
        )
        parsed = parse_api_envelope(envelope)
        self._logger.record_api_request_completed(
            request_id=parsed.request_id,
            session_id=context.session_id,
            trace_id=parsed.trace_id or trace_id,
            user_id=context.user_id,
            route="/api/v1/chat/query",
            duration_ms=(perf_counter() - start_time) * 1000,
            status="failed" if parsed.error is not None else "succeeded",
            error_code=None if parsed.error is None else parsed.error.code,
        )
        _raise_if_error_envelope(parsed)
        return build_query_result_view_model(parsed.as_mapping())

    def load_history(
        self,
        context: FrontendUserContext,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> HistoryListViewModel:
        """GET paginated query history for the History page."""

        envelope = self._transport.get_json(
            path="/api/v1/chat/history",
            headers=_headers(context=context, trace_id=new_trace_id()),
            query={
                "user_id": context.user_id,
                "page_size": str(page_size),
                **({"cursor": cursor} if cursor is not None else {}),
            },
        )
        parsed = parse_api_envelope(envelope)
        _raise_if_error_envelope(parsed)
        data = _data(parsed)
        return HistoryListViewModel(
            items=tuple(_list(data.get("items"), field_name="data.items")),
            next_cursor=_optional_string(data.get("next_cursor"), field_name="data.next_cursor"),
            page_size=int(data.get("page_size", page_size)),
        )

    def replay_query(
        self,
        context: FrontendUserContext,
        trace_id: str,
    ) -> QueryResultViewModel:
        """GET one previous answer and convert it into the same result cards."""

        envelope = self._transport.get_json(
            path=f"/api/v1/query/{trace_id}",
            headers=_headers(context=context, trace_id=new_trace_id()),
            query={"user_id": context.user_id},
        )
        parsed = parse_api_envelope(envelope)
        _raise_if_error_envelope(parsed)
        data = _data(parsed)
        answer = _mapping(data.get("answer"), field_name="data.answer")
        replay_envelope = {
            "data": answer,
            "trace_id": trace_id,
            "warnings": parsed.warnings,
            "error": None,
            "request_id": parsed.request_id,
        }
        return build_query_result_view_model(replay_envelope)

    def load_metric_catalog(self, context: FrontendUserContext) -> MetricCatalogViewModel:
        """GET metric definitions for the Catalog page."""

        envelope = self._transport.get_json(
            path="/api/v1/metrics/catalog",
            headers=_headers(context=context, trace_id=new_trace_id()),
            query={"user_id": context.user_id},
        )
        parsed = parse_api_envelope(envelope)
        _raise_if_error_envelope(parsed)
        data = _data(parsed)
        return MetricCatalogViewModel(
            metrics=tuple(_list(data.get("metrics"), field_name="data.metrics")),
        )

    def load_task_status(
        self,
        context: FrontendUserContext,
        task_id: str,
    ) -> TaskStatusViewModel:
        """GET one long-running task status by task id."""

        envelope = self._transport.get_json(
            path=f"/api/v1/chat/tasks/{task_id}",
            headers=_headers(context=context, trace_id=new_trace_id()),
            query={"user_id": context.user_id},
        )
        parsed = parse_api_envelope(envelope)
        _raise_if_error_envelope(parsed)
        return build_task_status_view_model(_data(parsed), context.locale)

    def analyze_metric(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> FrontendAnalyticsResultViewModel:
        """POST analytics v2 request and return the typed frontend result."""

        envelope = self._transport.post_json(
            path="/api/v2/analytics/analyze",
            headers=_headers(context=context, trace_id=request.trace_id),
            body=request.as_body(),
        )
        parsed = parse_api_envelope(envelope)
        _raise_if_error_envelope(parsed)
        return _analytics_result_view_model(_data(parsed))

    def enqueue_analytics(
        self,
        context: FrontendUserContext,
        request: FrontendAnalyticsRequest,
    ) -> TaskStatusViewModel:
        """POST analytics v2 request as a long-running task."""

        envelope = self._transport.post_json(
            path="/api/v2/analytics/tasks",
            headers=_headers(context=context, trace_id=request.trace_id),
            body=request.as_body(),
        )
        parsed = parse_api_envelope(envelope)
        _raise_if_error_envelope(parsed)
        return build_task_status_view_model(_data(parsed), context.locale)

    def load_analytics_result(
        self,
        context: FrontendUserContext,
        trace_id: str,
    ) -> FrontendAnalyticsResultViewModel:
        """GET one persisted analytics v2 result by trace id."""

        envelope = self._transport.get_json(
            path=f"/api/v2/analytics/results/{trace_id}",
            headers=_headers(context=context, trace_id=trace_id),
        )
        parsed = parse_api_envelope(envelope)
        _raise_if_error_envelope(parsed)
        return _analytics_result_view_model(_data(parsed))

    def run_evaluation(
        self,
        context: FrontendUserContext,
        eval_suite_id: str,
        questions: tuple[str, ...] = (),
    ) -> EvaluationRunViewModel:
        """POST an evaluation run and return the quality report."""

        envelope = self._transport.post_json(
            path="/api/v1/evals/run",
            headers=_headers(context=context, trace_id=new_trace_id()),
            query={"user_id": context.user_id},
            body={
                "eval_suite_id": eval_suite_id,
                "questions": questions,
                "locale": context.locale.value,
                "role": context.role.value,
            },
        )
        parsed = parse_api_envelope(envelope)
        _raise_if_error_envelope(parsed)
        data = _data(parsed)
        return EvaluationRunViewModel(
            eval_run_id=_string(data.get("eval_run_id"), field_name="data.eval_run_id"),
            eval_suite_id=_string(data.get("eval_suite_id"), field_name="data.eval_suite_id"),
            total_cases=_int(data.get("total_cases"), field_name="data.total_cases"),
            passed_cases=_int(data.get("passed_cases"), field_name="data.passed_cases"),
            failed_cases=_int(data.get("failed_cases"), field_name="data.failed_cases"),
            overall_score=_float(data.get("overall_score"), field_name="data.overall_score"),
            average_confidence=_float(
                data.get("average_confidence"),
                field_name="data.average_confidence",
            ),
            metric_breakdown=_float_mapping(
                data.get("metric_breakdown"),
                field_name="data.metric_breakdown",
            ),
            failed_cases_detail=_list(
                data.get("failed_cases_detail"),
                field_name="data.failed_cases_detail",
            ),
            release_gate_passed=_bool(
                data.get("release_gate_passed"),
                field_name="data.release_gate_passed",
            ),
        )


def _headers(
    context: FrontendUserContext,
    trace_id: str,
    idempotency_key: str | None = None,
) -> Mapping[str, str]:
    request_id = _request_id_from_trace_id(trace_id)
    headers = {
        "Authorization": f"Bearer {context.bearer_token}",
        "X-Trace-Id": trace_id,
        "X-Request-Id": request_id,
        "X-Session-Id": context.session_id,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def parse_api_envelope(raw: Mapping[str, Any]) -> FrontendApiEnvelope:
    """Parse the Backend API envelope used by the frontend.

    The v2 contract is data/warnings/error/trace_id/request_id. During the
    migration we also accept the older code/message envelope and normalize it
    to the same frontend shape.
    """

    if "error" in raw or "request_id" in raw:
        return _parse_v2_envelope(raw)
    return _parse_legacy_envelope(raw)


def _raise_if_error_envelope(envelope: FrontendApiEnvelope) -> None:
    if envelope.error is not None:
        raise FrontendApiException(
            error=envelope.error,
            trace_id=envelope.trace_id,
            request_id=envelope.request_id,
        )


def _parse_v2_envelope(raw: Mapping[str, Any]) -> FrontendApiEnvelope:
    error = _api_error(raw.get("error"))
    return FrontendApiEnvelope(
        data=_optional_mapping(raw.get("data"), field_name="data"),
        warnings=_list(raw.get("warnings", ()), field_name="warnings"),
        error=error,
        trace_id=_optional_string(raw.get("trace_id"), field_name="trace_id"),
        request_id=_string(raw.get("request_id"), field_name="request_id"),
    )


def _parse_legacy_envelope(raw: Mapping[str, Any]) -> FrontendApiEnvelope:
    trace_id = _optional_string(raw.get("trace_id"), field_name="trace_id")
    code = raw.get("code")
    error = None
    if code != 0:
        error = FrontendApiError(
            code=str(code or "INTERNAL_ERROR"),
            message=str(raw.get("message") or "Backend API request failed."),
            retryable=False,
        )

    return FrontendApiEnvelope(
        data=_optional_mapping(raw.get("data"), field_name="data"),
        warnings=_list(raw.get("warnings", ()), field_name="warnings"),
        error=error,
        trace_id=trace_id,
        request_id=_optional_string(raw.get("request_id"), field_name="request_id")
        or _request_id_from_trace_id(trace_id or "frontend"),
    )


def _api_error(value: object) -> FrontendApiError | None:
    if value is None:
        return None
    error = _mapping(value, field_name="error")
    return FrontendApiError(
        code=_string(error.get("code"), field_name="error.code"),
        message=_string(error.get("message"), field_name="error.message"),
        retryable=_bool(error.get("retryable"), field_name="error.retryable"),
    )


def _data(envelope: FrontendApiEnvelope) -> Mapping[str, Any]:
    return _mapping(envelope.data, field_name="data")


def _analytics_result_view_model(data: Mapping[str, Any]) -> FrontendAnalyticsResultViewModel:
    result = _mapping(data.get("result"), field_name="data.result")
    return FrontendAnalyticsResultViewModel(
        trace_id=_string(data.get("trace_id"), field_name="data.trace_id"),
        metric_id=_string(data.get("metric_id"), field_name="data.metric_id"),
        semantic_version_id=_string(
            data.get("semantic_version_id"),
            field_name="data.semantic_version_id",
        ),
        method=_string(result.get("method"), field_name="result.method"),
        model_version=_string(result.get("model_version"), field_name="result.model_version"),
        anomaly_points=_list(
            result.get("anomaly_points", ()),
            field_name="result.anomaly_points",
        ),
        forecast_points=_list(
            result.get("forecast_points", ()),
            field_name="result.forecast_points",
        ),
        quality_warnings=_string_tuple(
            result.get("quality_warnings", ()),
            field_name="result.quality_warnings",
        ),
        explanation=_string(result.get("explanation"), field_name="result.explanation"),
    )


def _optional_mapping(value: object, field_name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    return _mapping(value, field_name=field_name)


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return cast(Mapping[str, Any], value)


def _list(value: object, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) and not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a list")
    items = cast(tuple[object, ...] | list[object], value)
    return tuple(_mapping(item, field_name=field_name) for item in items)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) and not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a list")
    items = cast(tuple[object, ...] | list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"{field_name} must contain strings")
    return cast(tuple[str, ...], tuple(items))


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    return value


def _request_id_from_trace_id(trace_id: str) -> str:
    if trace_id.startswith("trc_"):
        return f"req_{trace_id.removeprefix('trc_')}"
    if trace_id.startswith("tr_"):
        return f"req_{trace_id.removeprefix('tr_')}"
    return f"req_{trace_id}"


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _int(value: object, field_name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _float(value: object, field_name: str) -> float:
    if not isinstance(value, int) and not isinstance(value, float):
        raise ValueError(f"{field_name} must be a number")
    return float(value)


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _float_mapping(value: object, field_name: str) -> Mapping[str, float]:
    mapping = _mapping(value, field_name=field_name)
    return {
        _string(key, field_name=f"{field_name}.key"): _float(
            metric_value,
            field_name=f"{field_name}.{key}",
        )
        for key, metric_value in mapping.items()
    }
