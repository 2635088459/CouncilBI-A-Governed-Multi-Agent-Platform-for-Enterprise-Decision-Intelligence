"""Application entry points for the minimal Overall Architecture slice."""

from __future__ import annotations

from chatbi.api.models import (
    ApiEnvelope,
    ChatQueryRequestPayload,
    success_envelope,
    to_chat_query_response,
)
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator


class ChatBIApplication:
    """Small application facade for the chat query workflow."""

    def __init__(self, orchestrator: SimpleOrchestrator | None = None) -> None:
        self._orchestrator = orchestrator or SimpleOrchestrator()

    @property
    def orchestrator(self) -> SimpleOrchestrator:
        return self._orchestrator

    def handle_chat_query(self, payload: ChatQueryRequestPayload) -> ApiEnvelope:
        request = payload.to_domain()
        answer = self._orchestrator.answer(request)
        response = to_chat_query_response(answer)
        return success_envelope(response)
