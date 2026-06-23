"""History page state for browsing and replaying ChatBI queries.

The History page is a list view. It should know enough to show past questions
and choose one for replay, but it should not cache full answer payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Mapping, Protocol

from chatbi.frontend.api_client import FrontendUserContext, HistoryListViewModel


class HistoryItemStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HistoryItemViewModel:
    trace_id: str
    session_id: str
    question: str
    status: HistoryItemStatus
    created_at: str
    can_replay: bool


@dataclass(frozen=True, slots=True)
class ReplaySelection:
    trace_id: str
    question: str


@dataclass(frozen=True, slots=True)
class HistoryPageState:
    context: FrontendUserContext
    items: tuple[HistoryItemViewModel, ...] = ()
    next_cursor: str | None = None
    page_size: int = 20
    is_loading: bool = False
    error_message: str | None = None
    selected_replay: ReplaySelection | None = None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


class HistoryApiPort(Protocol):
    def load_history(
        self,
        context: FrontendUserContext,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> HistoryListViewModel:
        """Load one paginated history page from the Backend API."""
        ...


class HistoryPageStore:
    """Small in-memory store for the History page."""

    def __init__(
        self,
        context: FrontendUserContext,
        api_client: HistoryApiPort,
        page_size: int = 20,
    ) -> None:
        self._api_client = api_client
        self._state = HistoryPageState(context=context, page_size=page_size)

    @property
    def state(self) -> HistoryPageState:
        return self._state

    def load_first_page(self) -> HistoryPageState:
        """Replace the list with the first history page."""

        self._state = replace(
            self._state,
            is_loading=True,
            error_message=None,
            selected_replay=None,
        )
        return self._load(cursor=None, append=False)

    def load_next_page(self) -> HistoryPageState:
        """Append the next page when the backend gives us a cursor."""

        if self._state.next_cursor is None:
            return self._state

        self._state = replace(
            self._state,
            is_loading=True,
            error_message=None,
        )
        return self._load(cursor=self._state.next_cursor, append=True)

    def select_for_replay(self, trace_id: str) -> HistoryPageState:
        """Choose a successful history item that Chat page can replay."""

        item = self._find_item(trace_id)
        if item is None:
            self._state = replace(
                self._state,
                selected_replay=None,
                error_message="History item was not found.",
            )
            return self._state

        if not item.can_replay:
            self._state = replace(
                self._state,
                selected_replay=None,
                error_message="Only successful queries can be replayed.",
            )
            return self._state

        self._state = replace(
            self._state,
            selected_replay=ReplaySelection(
                trace_id=item.trace_id,
                question=item.question,
            ),
            error_message=None,
        )
        return self._state

    def clear_selection(self) -> HistoryPageState:
        self._state = replace(self._state, selected_replay=None)
        return self._state

    def _load(self, cursor: str | None, append: bool) -> HistoryPageState:
        try:
            page = self._api_client.load_history(
                context=self._state.context,
                cursor=cursor,
                page_size=self._state.page_size,
            )
        except ValueError as exc:
            self._state = replace(
                self._state,
                is_loading=False,
                error_message=str(exc),
            )
            return self._state

        new_items = tuple(_history_item(raw_item) for raw_item in page.items)
        items = (*self._state.items, *new_items) if append else new_items
        self._state = replace(
            self._state,
            items=items,
            next_cursor=page.next_cursor,
            page_size=page.page_size,
            is_loading=False,
            error_message=None,
        )
        return self._state

    def _find_item(self, trace_id: str) -> HistoryItemViewModel | None:
        for item in self._state.items:
            if item.trace_id == trace_id:
                return item
        return None


def _history_item(raw_item: Mapping[str, Any]) -> HistoryItemViewModel:
    status = HistoryItemStatus(_string(raw_item.get("status"), field_name="status"))
    return HistoryItemViewModel(
        trace_id=_string(raw_item.get("trace_id"), field_name="trace_id"),
        session_id=_string(raw_item.get("session_id"), field_name="session_id"),
        question=_string(raw_item.get("question"), field_name="question"),
        status=status,
        created_at=_string(raw_item.get("created_at"), field_name="created_at"),
        can_replay=status is HistoryItemStatus.SUCCEEDED,
    )


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value
