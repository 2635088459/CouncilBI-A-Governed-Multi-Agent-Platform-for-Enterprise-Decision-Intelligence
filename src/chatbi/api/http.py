"""FastAPI entry point for the Backend API slice."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from chatbi.api.models import (
    ApiEnvelope,
    ApiErrorCode,
    ChatQueryRequestPayload,
    EvalRunRequestPayload,
    error_envelope,
)
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import Locale, UserRole, new_trace_id


# Request body models translate HTTP JSON into API contract dataclasses.
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


class EvalRunRequestBody(BaseModel):
    eval_suite_id: str = "backend_api_smoke"
    questions: tuple[str, ...] = ()
    locale: Locale = Locale.EN
    role: UserRole = UserRole.ANALYST

    def to_payload(self) -> EvalRunRequestPayload:
        return EvalRunRequestPayload(
            eval_suite_id=self.eval_suite_id,
            questions=self.questions,
            locale=self.locale,
            role=self.role,
        )


# Response helpers keep every endpoint on the unified envelope contract.
def envelope_to_dict(envelope: ApiEnvelope) -> dict[str, Any]:
    return asdict(envelope)


def response_from_envelope(envelope: ApiEnvelope, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=envelope_to_dict(envelope),
    )


def status_code_for_envelope(envelope: ApiEnvelope) -> int:
    if envelope.code is ApiErrorCode.RATE_LIMITED:
        return 429
    if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT:
        return 400
    if envelope.code is ApiErrorCode.AUTH_UNAUTHORIZED:
        return 401
    if envelope.code is ApiErrorCode.AUTH_FORBIDDEN:
        return 403
    return 200


# Header validation is the front-door policy for Backend API v1.
def require_headers(
    application: ChatBIApplication,
    endpoint: str,
    trace_id: str | None,
    authorization: str | None,
) -> tuple[str, JSONResponse | None]:
    active_trace_id = trace_id or new_trace_id()
    if trace_id is None or not trace_id.strip():
        envelope = error_envelope(
            code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            message="X-Trace-Id header is required.",
            trace_id=active_trace_id,
        )
        application.record_api_audit(
            trace_id=active_trace_id,
            user_id="anonymous",
            endpoint=endpoint,
            status_code=400,
            error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
        )
        return active_trace_id, response_from_envelope(envelope, status_code=400)

    if authorization is None or not authorization.startswith("Bearer "):
        envelope = error_envelope(
            code=ApiErrorCode.AUTH_UNAUTHORIZED,
            message="Missing or invalid bearer token.",
            trace_id=active_trace_id,
        )
        application.record_api_audit(
            trace_id=active_trace_id,
            user_id="anonymous",
            endpoint=endpoint,
            status_code=401,
            error_code=ApiErrorCode.AUTH_UNAUTHORIZED,
        )
        return active_trace_id, response_from_envelope(envelope, status_code=401)

    return active_trace_id, None


# Route registration is intentionally thin: validate HTTP concerns, call the
# application facade, then serialize one ApiEnvelope back to the client.
def create_app(application: ChatBIApplication | None = None) -> FastAPI:
    chatbi_application = application or ChatBIApplication()
    app = FastAPI(title="Governed ChatBI Platform", version="0.1.0")

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        trace_id = request.headers.get("x-trace-id") or new_trace_id()
        envelope = error_envelope(
            code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            message="Request payload or parameters are invalid.",
            trace_id=trace_id,
            data={"details": exc.errors()},
        )
        chatbi_application.record_api_audit(
            trace_id=trace_id,
            user_id="anonymous",
            endpoint=str(request.url.path),
            status_code=400,
            error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
        )
        return response_from_envelope(envelope, status_code=400)

    @app.post("/api/v1/chat/query")
    def chat_query(  # pyright: ignore[reportUnusedFunction]
        body: ChatQueryRequestBody,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/chat/query",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_chat_query(
            body.to_payload(),
            trace_id=active_trace_id,
            idempotency_key=idempotency_key,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/chat/history")
    def chat_history(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        cursor: str | None = None,
        page_size: int = 20,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/chat/history",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_chat_history(
            user_id=user_id,
            trace_id=active_trace_id,
            cursor=cursor,
            page_size=page_size,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/query/{trace_id}")
    def query_detail(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        _, rejected = require_headers(
            chatbi_application,
            f"/api/v1/query/{trace_id}",
            request_trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_query_detail(trace_id=trace_id, user_id=user_id)
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/metrics/catalog")
    def metrics_catalog(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/metrics/catalog",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_metrics_catalog(
            user_id=user_id,
            trace_id=active_trace_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/datasets/catalog")
    def datasets_catalog(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/datasets/catalog",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_datasets_catalog(
            user_id=user_id,
            trace_id=active_trace_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/audit/{trace_id}")
    def audit_detail(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        _, rejected = require_headers(
            chatbi_application,
            f"/api/v1/audit/{trace_id}",
            request_trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_audit_detail(trace_id=trace_id, user_id=user_id)
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/observability/traces/{trace_id}")
    def observability_trace_detail(  # pyright: ignore[reportUnusedFunction]
        trace_id: str,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        request_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        _, rejected = require_headers(
            chatbi_application,
            f"/api/v1/observability/traces/{trace_id}",
            request_trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_observability_trace_detail(
            trace_id=trace_id,
            user_id=user_id,
        )
        status_code = 404 if envelope.code is ApiErrorCode.REQ_INVALID_ARGUMENT else status_code_for_envelope(envelope)
        return response_from_envelope(envelope, status_code=status_code)

    @app.get("/api/v1/quality/dashboard")
    def quality_dashboard(  # pyright: ignore[reportUnusedFunction]
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/quality/dashboard",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_quality_dashboard(
            user_id=user_id,
            trace_id=active_trace_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.post("/api/v1/evals/run")
    def eval_run(  # pyright: ignore[reportUnusedFunction]
        body: EvalRunRequestBody,
        user_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/evals/run",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_eval_run(
            user_id=user_id,
            trace_id=active_trace_id,
            payload=body.to_payload(),
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    @app.get("/api/v1/health")
    def health(  # pyright: ignore[reportUnusedFunction]
        user_id: str = "system",
        authorization: str | None = Header(default=None, alias="Authorization"),
        trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> JSONResponse:
        active_trace_id, rejected = require_headers(
            chatbi_application,
            "/api/v1/health",
            trace_id,
            authorization,
        )
        if rejected is not None:
            return rejected

        envelope = chatbi_application.handle_health_check(
            user_id=user_id,
            trace_id=active_trace_id,
        )
        return response_from_envelope(envelope, status_code=status_code_for_envelope(envelope))

    return app


app = create_app()
