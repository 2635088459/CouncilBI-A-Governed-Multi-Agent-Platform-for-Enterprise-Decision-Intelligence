"""Masked observability log records for spec 10.

Trace spans tell us what happened in the request path. Log records add short
human-readable notes, but they must never store raw PII.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from typing import Any, Mapping, cast

from chatbi.core.contracts import utc_now


def _empty_log_attributes() -> Mapping[str, Any]:
    return {}


class LogLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ObservabilityLogRecord:
    trace_id: str
    level: LogLevel
    message: str
    endpoint: str
    user_id: str
    attributes: Mapping[str, Any] = field(default_factory=_empty_log_attributes)
    recorded_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")


class LogSanitizer:
    """Mask PII in log messages and structured attributes."""

    _email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    _phone_pattern = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
    _sensitive_key_tokens = frozenset(
        {
            "customer_id",
            "customer_name",
            "email",
            "phone",
            "session_id",
            "user_email",
            "user_id",
        }
    )

    def sanitize_message(self, message: str) -> str:
        return self._sanitize_text(message)

    def sanitize_user_id(self, user_id: str) -> str:
        if not user_id:
            return "[masked-user]"
        return "[masked-user]"

    def sanitize_attributes(self, attributes: Mapping[str, Any]) -> Mapping[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in attributes.items():
            if self._is_sensitive_key(key):
                sanitized[key] = self._mask_sensitive_value(key, value)
            else:
                sanitized[key] = self._sanitize_value(value)
        return sanitized

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._sanitize_text(value)
        if isinstance(value, Mapping):
            return self.sanitize_attributes(cast(Mapping[str, Any], value))
        if isinstance(value, tuple):
            tuple_value = cast(tuple[Any, ...], value)
            return tuple(self._sanitize_value(item) for item in tuple_value)
        if isinstance(value, list):
            list_value = cast(list[Any], value)
            return [self._sanitize_value(item) for item in list_value]
        return value

    def _sanitize_text(self, text: str) -> str:
        masked_email_text = self._email_pattern.sub("[masked-email]", text)
        return self._phone_pattern.sub("[masked-phone]", masked_email_text)

    def _is_sensitive_key(self, key: str) -> bool:
        normalized_key = key.strip().lower()
        return any(token in normalized_key for token in self._sensitive_key_tokens)

    def _mask_sensitive_value(self, key: str, value: Any) -> Any:
        if value is None:
            return None

        normalized_key = key.strip().lower()
        if "email" in normalized_key:
            return "[masked-email]"
        if "phone" in normalized_key:
            return "[masked-phone]"
        if "customer_name" in normalized_key:
            return "[masked-name]"
        if "session_id" in normalized_key:
            return "[masked-session]"
        if "user_id" in normalized_key:
            return "[masked-user]"
        if "customer_id" in normalized_key:
            return "[masked-customer]"
        return "[masked]"


class InMemoryObservabilityLogStore:
    """Small append-only log store for local runtime and tests."""

    def __init__(self) -> None:
        self._records: list[ObservabilityLogRecord] = []

    def add(self, record: ObservabilityLogRecord) -> None:
        self._records.append(record)

    def list_by_trace_id(self, trace_id: str) -> tuple[ObservabilityLogRecord, ...]:
        return tuple(record for record in self._records if record.trace_id == trace_id)

    def list_all(self) -> tuple[ObservabilityLogRecord, ...]:
        return tuple(self._records)


class ObservabilityLogger:
    """Create sanitized observability log records."""

    def __init__(
        self,
        store: InMemoryObservabilityLogStore | None = None,
        sanitizer: LogSanitizer | None = None,
    ) -> None:
        self._store = store or InMemoryObservabilityLogStore()
        self._sanitizer = sanitizer or LogSanitizer()

    @property
    def store(self) -> InMemoryObservabilityLogStore:
        return self._store

    def record(
        self,
        trace_id: str,
        level: LogLevel,
        message: str,
        endpoint: str,
        user_id: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> ObservabilityLogRecord:
        active_attributes: Mapping[str, Any] = attributes if attributes is not None else {}
        record = ObservabilityLogRecord(
            trace_id=trace_id,
            level=level,
            message=self._sanitizer.sanitize_message(message),
            endpoint=endpoint,
            user_id=self._sanitizer.sanitize_user_id(user_id),
            attributes=self._sanitizer.sanitize_attributes(active_attributes),
        )
        self._store.add(record)
        return record
