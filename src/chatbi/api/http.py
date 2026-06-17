"""FastAPI entry point for the minimal Overall Architecture slice."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from chatbi.api.models import ApiEnvelope, ChatQueryRequestPayload
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import Locale, UserRole


class ChatQueryRequestBody(BaseModel):
    user_id: str
    session_id: str
    question: str
    locale: Locale
    role: UserRole

    def to_payload(self) -> ChatQueryRequestPayload:
        return ChatQueryRequestPayload(
            user_id=self.user_id,
            session_id=self.session_id,
            question=self.question,
            locale=self.locale,
            role=self.role,
        )


def envelope_to_dict(envelope: ApiEnvelope) -> dict[str, Any]:
    return asdict(envelope)


def create_app(application: ChatBIApplication | None = None) -> FastAPI:
    chatbi_application = application or ChatBIApplication()
    app = FastAPI(title="Governed ChatBI Platform", version="0.1.0")

    @app.post("/api/v1/chat/query")
    def chat_query(body: ChatQueryRequestBody) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        envelope = chatbi_application.handle_chat_query(body.to_payload())
        return envelope_to_dict(envelope)

    return app


app = create_app()
