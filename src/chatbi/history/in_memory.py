"""In-memory query history store for the Overall Architecture workflow.

This implementation is useful for early TDD, demos, and local development.
It follows QueryHistoryPort but deliberately avoids database concerns.
"""

from __future__ import annotations

from chatbi.core.contracts import QueryHistoryRecord, QueryHistoryStatus


class InMemoryQueryHistory:
    """Save and replay query history records by trace id."""

    def __init__(self) -> None:
        self._records: dict[str, QueryHistoryRecord] = {}

    def save(self, record: QueryHistoryRecord) -> None:
        self._records[record.trace_id] = record

    def get(self, trace_id: str) -> QueryHistoryRecord | None:
        return self._records.get(trace_id)

    def list_all(self) -> tuple[QueryHistoryRecord, ...]:
        return tuple(self._records.values())

    def list_by_status(self, status: QueryHistoryStatus) -> tuple[QueryHistoryRecord, ...]:
        return tuple(record for record in self._records.values() if record.status is status)
