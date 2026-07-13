"""Version 2 architecture boundary contracts.

This file follows ``spec/version2/01-overall-architecture.spec.md``. It is the
thin contract layer between Frontend Web and Backend API: request ids, session
ids, response envelopes, warnings, errors, and answer payloads are named here
before service code starts moving data around.
"""

from __future__ import annotations

import re
from typing import Any, Literal, NotRequired, TypedDict, cast


UserRoleV2 = Literal["business_user", "analyst", "admin"]
LocaleV2 = Literal["en", "zh-CN"]

REQUEST_ID_PATTERN = re.compile(r"^req_[A-Za-z0-9_-]{8,64}$")
SESSION_ID_PATTERN = re.compile(r"^ses_[A-Za-z0-9_-]{8,64}$")
TRACE_ID_PATTERN = re.compile(r"^tr_[A-Za-z0-9_-]{8,64}$")


class TableResultV2(TypedDict):
    columns: list[str]
    rows: list[dict[str, Any]]


class EvidenceItemV2(TypedDict):
    source_id: str
    title: str
    citation_anchor: str
    snippet: str
    relevance_score: float


class WarningPayloadV2(TypedDict):
    code: str
    message: str
    field: NotRequired[str | None]


class ErrorPayloadV2(TypedDict):
    code: str
    message: str
    retryable: bool
    detail: NotRequired[dict[str, Any] | None]


class AnswerPayloadV2(TypedDict):
    answer_text: str
    table_result: TableResultV2 | None
    chart_spec: dict[str, Any] | None
    evidence_list: list[EvidenceItemV2]
    agent_timeline: NotRequired[list[dict[str, Any]]]
    confidence: float
    # FR-FV10-024/025: which data source a table_result came from, so the
    # frontend can show the "文件数据" badge; FR-FV10-019/AC-FV10-009: set
    # when a file-data query's SQL was blocked by the guardrail instead of
    # ever reaching DuckDB.
    table_result_source: NotRequired[str | None]
    guardrail_blocked: NotRequired[bool]
    analytics_result: NotRequired[dict[str, Any] | None]


class ChatQueryRequestV2(TypedDict):
    request_id: str
    session_id: str
    user_id: str
    role: UserRoleV2
    locale: LocaleV2
    question: str


class ChatQueryResponseV2(TypedDict):
    trace_id: str
    data: AnswerPayloadV2 | None
    warnings: list[WarningPayloadV2]
    error: ErrorPayloadV2 | None
    request_id: str


def validate_chat_query_request_v2(payload: dict[str, Any]) -> list[WarningPayloadV2]:
    """Return validation problems for the v2 chat query request contract."""

    problems: list[WarningPayloadV2] = []
    _require_pattern(
        payload=payload,
        field_name="request_id",
        pattern=REQUEST_ID_PATTERN,
        problems=problems,
        message="request_id must look like req_<8-64 letters, numbers, underscores, or hyphens>.",
    )
    _require_pattern(
        payload=payload,
        field_name="session_id",
        pattern=SESSION_ID_PATTERN,
        problems=problems,
        message="session_id must look like ses_<8-64 letters, numbers, underscores, or hyphens>.",
    )
    _require_string_length(payload, "user_id", min_length=1, max_length=128, problems=problems)
    _require_literal(
        payload=payload,
        field_name="role",
        allowed=("business_user", "analyst", "admin"),
        problems=problems,
    )
    _require_literal(
        payload=payload,
        field_name="locale",
        allowed=("en", "zh-CN"),
        problems=problems,
    )
    _require_string_length(payload, "question", min_length=1, max_length=2000, problems=problems)
    return problems


def validate_chat_query_response_v2(payload: dict[str, Any]) -> list[WarningPayloadV2]:
    """Return validation problems for the v2 Backend API response envelope."""

    problems: list[WarningPayloadV2] = []
    _require_pattern(
        payload=payload,
        field_name="trace_id",
        pattern=TRACE_ID_PATTERN,
        problems=problems,
        message="trace_id must look like tr_<8-64 letters, numbers, underscores, or hyphens>.",
    )
    _require_pattern(
        payload=payload,
        field_name="request_id",
        pattern=REQUEST_ID_PATTERN,
        problems=problems,
        message="request_id must look like req_<8-64 letters, numbers, underscores, or hyphens>.",
    )
    if "warnings" not in payload or not isinstance(payload["warnings"], list):
        problems.append(_problem("VALIDATION_ERROR", "warnings must be a list.", "warnings"))
    if "error" not in payload:
        problems.append(_problem("VALIDATION_ERROR", "error is required and may be null.", "error"))

    data = payload.get("data")
    error = payload.get("error")
    if data is None and error is None:
        problems.append(
            _problem(
                "VALIDATION_ERROR",
                "response must include either data or error.",
                "data",
            )
        )
    if data is not None:
        if not isinstance(data, dict):
            problems.append(_problem("VALIDATION_ERROR", "data must be an object or null.", "data"))
        else:
            problems.extend(validate_answer_payload_v2(cast(dict[str, Any], data)))
    return problems


def validate_answer_payload_v2(payload: dict[str, Any]) -> list[WarningPayloadV2]:
    """Return validation problems for the answer portion of a v2 response."""

    problems: list[WarningPayloadV2] = []
    _require_string_length(payload, "answer_text", min_length=1, max_length=None, problems=problems)
    if "table_result" not in payload:
        problems.append(
            _problem("VALIDATION_ERROR", "table_result is required and may be null.", "table_result")
        )
    elif payload["table_result"] is not None and not isinstance(payload["table_result"], dict):
        problems.append(
            _problem("VALIDATION_ERROR", "table_result must be an object or null.", "table_result")
        )
    if "chart_spec" not in payload:
        problems.append(_problem("VALIDATION_ERROR", "chart_spec is required and may be null.", "chart_spec"))
    elif payload["chart_spec"] is not None and not isinstance(payload["chart_spec"], dict):
        problems.append(_problem("VALIDATION_ERROR", "chart_spec must be an object or null.", "chart_spec"))
    if "evidence_list" not in payload or not isinstance(payload["evidence_list"], list):
        problems.append(_problem("VALIDATION_ERROR", "evidence_list must be a list.", "evidence_list"))

    confidence = payload.get("confidence")
    if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        problems.append(
            _problem("VALIDATION_ERROR", "confidence must be a number between 0.0 and 1.0.", "confidence")
        )
    return problems


def validation_error_response_v2(
    request_id: str,
    trace_id: str,
    problems: list[WarningPayloadV2],
) -> ChatQueryResponseV2:
    """Build the standard v2 error envelope for rejected frontend requests."""

    return {
        "trace_id": trace_id,
        "request_id": request_id,
        "data": None,
        "warnings": problems,
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Request payload did not match the v2 chat query contract.",
            "retryable": False,
            "detail": {"problems": problems},
        },
    }


def _require_pattern(
    payload: dict[str, Any],
    field_name: str,
    pattern: re.Pattern[str],
    problems: list[WarningPayloadV2],
    message: str,
) -> None:
    value = payload.get(field_name)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        problems.append(_problem("VALIDATION_ERROR", message, field_name))


def _require_string_length(
    payload: dict[str, Any],
    field_name: str,
    min_length: int,
    max_length: int | None,
    problems: list[WarningPayloadV2],
) -> None:
    value = payload.get(field_name)
    if not isinstance(value, str):
        problems.append(_problem("VALIDATION_ERROR", f"{field_name} must be a string.", field_name))
        return

    length = len(value)
    if length < min_length:
        problems.append(
            _problem("VALIDATION_ERROR", f"{field_name} must be at least {min_length} character(s).", field_name)
        )
    if max_length is not None and length > max_length:
        problems.append(
            _problem("VALIDATION_ERROR", f"{field_name} must be at most {max_length} character(s).", field_name)
        )


def _require_literal(
    payload: dict[str, Any],
    field_name: str,
    allowed: tuple[str, ...],
    problems: list[WarningPayloadV2],
) -> None:
    if payload.get(field_name) not in allowed:
        joined = ", ".join(allowed)
        problems.append(_problem("VALIDATION_ERROR", f"{field_name} must be one of: {joined}.", field_name))


def _problem(code: str, message: str, field: str) -> WarningPayloadV2:
    return {
        "code": code,
        "message": message,
        "field": field,
    }
