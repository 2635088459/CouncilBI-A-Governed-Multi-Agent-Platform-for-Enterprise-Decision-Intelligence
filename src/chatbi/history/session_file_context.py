"""Spec FV10.4 §6.4: session-scoped file_ids inheritance (FR-FV10-055).

Independent of ``InMemoryQueryHistory``'s bounded conversation-context
window (§6.1) — a session can stay attached to the same file for far more
turns than that window retains, so this tracks exactly one small piece of
state per session: the most recently *explicitly* supplied non-empty
``file_ids``.
"""

from __future__ import annotations

from typing import Protocol


class SessionFileContext(Protocol):
    def get_active_file_ids(self, session_id: str) -> tuple[str, ...]:
        """The most recently explicitly-supplied non-empty file_ids for this
        session, or () if none.
        """
        ...

    def set_active_file_ids(self, session_id: str, file_ids: tuple[str, ...]) -> None:
        """Record file_ids as the session's new inherited value. Only called
        with non-empty file_ids.
        """
        ...


class InMemorySessionFileContext:
    """Process-local ``SessionFileContext`` keyed by ``session_id``."""

    def __init__(self) -> None:
        self._active_file_ids_by_session: dict[str, tuple[str, ...]] = {}

    def get_active_file_ids(self, session_id: str) -> tuple[str, ...]:
        return self._active_file_ids_by_session.get(session_id, ())

    def set_active_file_ids(self, session_id: str, file_ids: tuple[str, ...]) -> None:
        self._active_file_ids_by_session[session_id] = file_ids


def resolve_effective_file_ids(
    explicit_file_ids: tuple[str, ...],
    session_id: str,
    session_file_context: SessionFileContext,
) -> tuple[str, ...]:
    """FR-FV10-055: explicit file_ids always win and become the new inherited
    value; otherwise inherit the session's current value, or () if none.
    """

    if explicit_file_ids:
        session_file_context.set_active_file_ids(session_id, explicit_file_ids)
        return explicit_file_ids
    return session_file_context.get_active_file_ids(session_id)
