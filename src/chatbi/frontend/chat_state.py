"""Chat page state management for the Frontend ChatBI slice.

The API client knows how to talk to the backend. View models know how to
render one answer. This file connects them into a page-level conversation:
user turn in, loading state on, answer card out.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.view_models import (
    MessageBubbleViewModel,
    MessageRole,
    QueryResultViewModel,
)


class ChatTurnStatus(StrEnum):
    SUBMITTED = "submitted"
    ANSWERED = "answered"
    FAILED = "failed"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class ChatTurnViewModel:
    question: MessageBubbleViewModel
    status: ChatTurnStatus
    result: QueryResultViewModel | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ChatPageState:
    context: FrontendUserContext
    turns: tuple[ChatTurnViewModel, ...] = ()
    is_loading: bool = False
    error_message: str | None = None

    @property
    def can_submit(self) -> bool:
        return not self.is_loading


class ChatApiPort(Protocol):
    def submit_question(
        self,
        context: FrontendUserContext,
        question: str,
        idempotency_key: str | None = None,
    ) -> QueryResultViewModel:
        """Submit a question through the backend API boundary."""
        ...

    def replay_query(
        self,
        context: FrontendUserContext,
        trace_id: str,
    ) -> QueryResultViewModel:
        """Load a previous query answer by trace id."""
        ...


class ChatSessionStore:
    """Small in-memory store for one Chat page session.

    It intentionally does not persist table rows or answers to disk/local
    storage. The browser can render current results, but durable history stays
    behind the Backend API.
    """

    def __init__(
        self,
        context: FrontendUserContext,
        api_client: ChatApiPort,
    ) -> None:
        self._api_client = api_client
        self._state = ChatPageState(context=context)

    @property
    def state(self) -> ChatPageState:
        return self._state

    def submit_question(
        self,
        question: str,
        idempotency_key: str | None = None,
    ) -> ChatPageState:
        """Add a user question and attach the backend answer when it returns."""

        normalized_question = _normalize_question(question)
        pending_turn = ChatTurnViewModel(
            question=MessageBubbleViewModel(
                role=MessageRole.USER,
                text=normalized_question,
            ),
            status=ChatTurnStatus.SUBMITTED,
        )
        self._state = replace(
            self._state,
            turns=(*self._state.turns, pending_turn),
            is_loading=True,
            error_message=None,
        )

        try:
            result = self._api_client.submit_question(
                context=self._state.context,
                question=normalized_question,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            failed_turn = replace(
                pending_turn,
                status=ChatTurnStatus.FAILED,
                error_message=str(exc),
            )
            self._state = replace(
                self._state,
                turns=(*self._state.turns[:-1], failed_turn),
                is_loading=False,
                error_message=str(exc),
            )
            return self._state

        answered_turn = replace(
            pending_turn,
            status=ChatTurnStatus.ANSWERED,
            result=result,
        )
        self._state = replace(
            self._state,
            turns=(*self._state.turns[:-1], answered_turn),
            is_loading=False,
            error_message=None,
        )
        return self._state

    def replay_history_item(self, trace_id: str, question: str) -> ChatPageState:
        """Append a replayed historical answer to the current conversation."""

        normalized_question = _normalize_question(question)
        self._state = replace(self._state, is_loading=True, error_message=None)

        try:
            result = self._api_client.replay_query(
                context=self._state.context,
                trace_id=trace_id,
            )
        except ValueError as exc:
            self._state = replace(
                self._state,
                is_loading=False,
                error_message=str(exc),
            )
            return self._state

        replayed_turn = ChatTurnViewModel(
            question=MessageBubbleViewModel(
                role=MessageRole.USER,
                text=normalized_question,
                trace_id=trace_id,
            ),
            status=ChatTurnStatus.REPLAYED,
            result=result,
        )
        self._state = replace(
            self._state,
            turns=(*self._state.turns, replayed_turn),
            is_loading=False,
            error_message=None,
        )
        return self._state

    def reset(self) -> ChatPageState:
        self._state = ChatPageState(context=self._state.context)
        return self._state


def _normalize_question(question: str) -> str:
    normalized = question.strip()
    if not normalized:
        raise ValueError("Question is required.")
    return normalized
