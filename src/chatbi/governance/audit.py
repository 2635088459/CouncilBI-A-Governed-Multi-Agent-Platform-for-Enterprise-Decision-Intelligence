"""In-memory audit log for guardrail decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from chatbi.core.contracts import ErrorCode, GuardrailDecision, UserRole, utc_now


def new_audit_event_id() -> str:
    return f"aud_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class GuardrailAuditRecord:
    trace_id: str
    user_id: str
    role: UserRole
    original_sql: str
    decision: GuardrailDecision
    audit_event_id: str = field(default_factory=new_audit_event_id)
    occurred_at: datetime = field(default_factory=utc_now)
    safe_sql: str | None = None
    error_code: ErrorCode | None = None
    message: str | None = None


class GuardrailAuditLog(Protocol):
    def save(self, record: GuardrailAuditRecord) -> None:
        """Save one guardrail decision for audit and replay."""
        ...

    def get(self, trace_id: str) -> GuardrailAuditRecord | None:
        """Replay the latest guardrail decision by trace id."""
        ...


class InMemoryGuardrailAuditLog:
    """Small audit store used by tests and the local demo runtime."""

    def __init__(self) -> None:
        self._records: list[GuardrailAuditRecord] = []

    def save(self, record: GuardrailAuditRecord) -> None:
        self._records.append(record)

    def get(self, trace_id: str) -> GuardrailAuditRecord | None:
        for record in reversed(self._records):
            if record.trace_id == trace_id:
                return record
        return None

    def list_by_trace_id(self, trace_id: str) -> tuple[GuardrailAuditRecord, ...]:
        return tuple(record for record in self._records if record.trace_id == trace_id)

    def list_all(self) -> tuple[GuardrailAuditRecord, ...]:
        return tuple(self._records)
