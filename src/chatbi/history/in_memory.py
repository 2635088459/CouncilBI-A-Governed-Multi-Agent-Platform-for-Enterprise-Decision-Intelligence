"""In-memory query history store for the Overall Architecture workflow.

This implementation is useful for early TDD, demos, and local development.
It follows QueryHistoryPort but deliberately avoids database concerns.
"""

from __future__ import annotations

from typing import Mapping

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

    def list_by_session(self, session_id: str, *, limit: int = 5) -> tuple[QueryHistoryRecord, ...]:
        """Spec FV10.4 FR-FV10-051: most recent ``limit`` turns for one
        session, oldest first — ready to prepend as conversation context.
        """

        matches = sorted(
            (record for record in self._records.values() if record.request.session_id == session_id),
            key=lambda record: record.created_at,
        )
        return tuple(matches[-limit:]) if limit > 0 else ()


def conversation_messages(records: tuple[QueryHistoryRecord, ...]) -> tuple[Mapping[str, str], ...]:
    """Spec FV10.4 §6.2: alternating user/assistant messages, oldest first,
    ready to prepend to an LLM call's ``messages`` tuple. A record with no
    answer (a denied/failed turn) contributes only its question.
    """

    messages: list[Mapping[str, str]] = []
    for record in records:
        messages.append({"role": "user", "content": record.request.question})
        if record.answer is not None:
            messages.append({"role": "assistant", "content": record.answer.answer_text})
    return tuple(messages)


def conversation_context_text(records: tuple[QueryHistoryRecord, ...]) -> str:
    """A plain-text summary of prior turns for retrieval query text (RAG),
    which works with free text rather than a chat message list.
    """

    parts: list[str] = []
    for record in records:
        parts.append(record.request.question)
        if record.answer is not None:
            parts.append(record.answer.answer_text)
    return " ".join(parts)
