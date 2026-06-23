"""Frontend-facing client for the Backend API.

This is not an agent client and not a database client. It only knows Backend
API routes, which keeps the frontend boundary clean and matches spec/07.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, cast

from chatbi.core.contracts import Locale, UserRole, new_trace_id
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


class FrontendApiClient:
    def __init__(self, transport: JsonTransport) -> None:
        self._transport = transport

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
        _raise_if_error_envelope(envelope)
        return build_query_result_view_model(envelope)

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
        _raise_if_error_envelope(envelope)
        data = _data(envelope)
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
        _raise_if_error_envelope(envelope)
        data = _data(envelope)
        answer = _mapping(data.get("answer"), field_name="data.answer")
        replay_envelope = {
            "code": envelope["code"],
            "message": envelope["message"],
            "data": answer,
            "trace_id": trace_id,
            "warnings": envelope.get("warnings", ()),
            "timestamp": envelope["timestamp"],
        }
        return build_query_result_view_model(replay_envelope)

    def load_metric_catalog(self, context: FrontendUserContext) -> MetricCatalogViewModel:
        """GET metric definitions for the Catalog page."""

        envelope = self._transport.get_json(
            path="/api/v1/metrics/catalog",
            headers=_headers(context=context, trace_id=new_trace_id()),
            query={"user_id": context.user_id},
        )
        _raise_if_error_envelope(envelope)
        data = _data(envelope)
        return MetricCatalogViewModel(
            metrics=tuple(_list(data.get("metrics"), field_name="data.metrics")),
        )

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
        _raise_if_error_envelope(envelope)
        data = _data(envelope)
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
    headers = {
        "Authorization": f"Bearer {context.bearer_token}",
        "X-Trace-Id": trace_id,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _raise_if_error_envelope(envelope: Mapping[str, Any]) -> None:
    if envelope.get("code") != 0:
        message = str(envelope.get("message", "Backend API request failed."))
        raise ValueError(message)


def _data(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(envelope.get("data"), field_name="data")


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return cast(Mapping[str, Any], value)


def _list(value: object, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) and not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a list")
    items = cast(tuple[object, ...] | list[object], value)
    return tuple(_mapping(item, field_name=field_name) for item in items)


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    return value


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
