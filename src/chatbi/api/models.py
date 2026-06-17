"""API-facing models for the Overall Architecture contract.

These dataclasses keep the HTTP boundary explicit without introducing a web
framework yet. A future FastAPI layer can convert these shapes to Pydantic
models or reuse the same field names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from chatbi.core.contracts import (
    ChartSpec,
    EvidenceItem,
    Locale,
    QueryAnswer,
    QueryRequest,
    TableResult,
    UserRole,
    WarningMessage,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ChatQueryRequestPayload:
    user_id: str
    session_id: str
    question: str
    locale: Locale
    role: UserRole

    def to_domain(self) -> QueryRequest:
        return QueryRequest(
            user_id=self.user_id,
            session_id=self.session_id,
            question=self.question,
            locale=self.locale,
            role=self.role,
        )


@dataclass(frozen=True, slots=True)
class ChatQueryResponsePayload:
    answer_text: str
    sql_text: str
    table_result: TableResult
    trace_id: str
    chart_spec: ChartSpec | None = None
    evidence_list: tuple[EvidenceItem, ...] = ()
    confidence: float = 1.0
    warnings: tuple[WarningMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class ApiEnvelope:
    code: int
    message: str
    data: Mapping[str, Any] | None
    trace_id: str
    warnings: tuple[WarningMessage, ...] = ()
    timestamp: str = field(default_factory=utc_now_iso)


def to_chat_query_response(answer: QueryAnswer) -> ChatQueryResponsePayload:
    return ChatQueryResponsePayload(
        answer_text=answer.answer_text,
        sql_text=answer.sql_text,
        table_result=answer.table_result,
        trace_id=answer.trace_id,
        chart_spec=answer.chart_spec,
        evidence_list=answer.evidence_list,
        confidence=answer.confidence,
        warnings=answer.warnings,
    )


def success_envelope(response: ChatQueryResponsePayload) -> ApiEnvelope:
    return ApiEnvelope(
        code=0,
        message="ok",
        data={
            "answer_text": response.answer_text,
            "sql_text": response.sql_text,
            "table_result": response.table_result,
            "chart_spec": response.chart_spec,
            "evidence_list": response.evidence_list,
            "confidence": response.confidence,
        },
        trace_id=response.trace_id,
        warnings=response.warnings,
    )
