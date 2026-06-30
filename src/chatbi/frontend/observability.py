"""Frontend observability events for the ChatBI UI.

Backend logs describe API execution. These records describe browser-side UI
events, such as a user submitting a question. They intentionally keep a small
field set so tests can prove the required identifiers are always present.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FrontendEventName(StrEnum):
    QUERY_SUBMITTED = "query_submitted"
    API_REQUEST_COMPLETED = "api_request_completed"
    FRONTEND_EXCEPTION = "frontend_exception"


@dataclass(frozen=True, slots=True)
class FrontendLogRecord:
    event: FrontendEventName
    request_id: str
    session_id: str
    trace_id: str
    user_id: str
    route: str
    duration_ms: float | None = None
    status: str | None = None
    error_code: str | None = None
    message: str | None = None


class InMemoryFrontendLogStore:
    """Small append-only frontend log store for local tests and fixtures."""

    def __init__(self) -> None:
        self._records: list[FrontendLogRecord] = []

    def add(self, record: FrontendLogRecord) -> None:
        self._records.append(record)

    def list_all(self) -> tuple[FrontendLogRecord, ...]:
        return tuple(self._records)


class FrontendLogger:
    """Create frontend log records with spec/07 required fields."""

    def __init__(self, store: InMemoryFrontendLogStore | None = None) -> None:
        self._store = store or InMemoryFrontendLogStore()

    @property
    def store(self) -> InMemoryFrontendLogStore:
        return self._store

    def record_query_submitted(
        self,
        *,
        request_id: str,
        session_id: str,
        trace_id: str,
        user_id: str,
    ) -> FrontendLogRecord:
        record = FrontendLogRecord(
            event=FrontendEventName.QUERY_SUBMITTED,
            request_id=_required_string(request_id, "request_id"),
            session_id=_required_string(session_id, "session_id"),
            trace_id=_required_string(trace_id, "trace_id"),
            user_id=_required_string(user_id, "user_id"),
            route="/api/v1/chat/query",
        )
        self._store.add(record)
        return record

    def record_api_request_completed(
        self,
        *,
        request_id: str,
        session_id: str,
        trace_id: str,
        user_id: str,
        route: str,
        duration_ms: float,
        status: str,
        error_code: str | None = None,
    ) -> FrontendLogRecord:
        if duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        record = FrontendLogRecord(
            event=FrontendEventName.API_REQUEST_COMPLETED,
            request_id=_required_string(request_id, "request_id"),
            session_id=_required_string(session_id, "session_id"),
            trace_id=_required_string(trace_id, "trace_id"),
            user_id=_required_string(user_id, "user_id"),
            route=_required_string(route, "route"),
            duration_ms=duration_ms,
            status=_required_string(status, "status"),
            error_code=error_code,
        )
        self._store.add(record)
        return record

    def record_frontend_exception(
        self,
        *,
        request_id: str,
        session_id: str,
        trace_id: str,
        user_id: str,
        route: str,
        message: str,
        error_code: str = "FRONTEND_EXCEPTION",
    ) -> FrontendLogRecord:
        record = FrontendLogRecord(
            event=FrontendEventName.FRONTEND_EXCEPTION,
            request_id=_required_string(request_id, "request_id"),
            session_id=_required_string(session_id, "session_id"),
            trace_id=_required_string(trace_id, "trace_id"),
            user_id=_required_string(user_id, "user_id"),
            route=_required_string(route, "route"),
            status="failed",
            error_code=_required_string(error_code, "error_code"),
            message=_required_string(message, "message"),
        )
        self._store.add(record)
        return record


def _required_string(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized
