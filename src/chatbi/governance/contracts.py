"""Typed contracts for the v2 SQL guardrail layer.

These models follow ``spec/version2/04-sql-guardrail-and-governance.spec.md``.
They describe the boundary before the guardrail implementation rewrites SQL,
applies masking rules, or writes audit records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from chatbi.core.architecture_contracts import ErrorPayloadV2, UserRoleV2


MAX_SQL_TEXT_LENGTH = 20_000


class GuardrailDecisionStatus(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class GuardrailRuleCode(StrEnum):
    WRITE_OPERATION = "WRITE_OPERATION"
    MULTIPLE_STATEMENTS = "MULTIPLE_STATEMENTS"
    UNAUTHORIZED_OBJECT = "UNAUTHORIZED_OBJECT"
    ROW_LIMIT_REWRITE = "ROW_LIMIT_REWRITE"
    MASKING_REQUIRED = "MASKING_REQUIRED"


class MaskingStrategy(StrEnum):
    REDACT = "redact"
    HASH = "hash"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class GuardrailRequestV2:
    trace_id: str
    user_id: str
    role: UserRoleV2
    sql_text: str
    semantic_version_id: str

    def __post_init__(self) -> None:
        _require_non_empty("trace_id", self.trace_id)
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("semantic_version_id", self.semantic_version_id)
        _require_sql_text(self.sql_text)
        if self.role not in ("business_user", "analyst", "admin"):
            raise ValueError("role must be business_user, analyst, or admin")


@dataclass(frozen=True, slots=True)
class RuleHit:
    rule_code: GuardrailRuleCode
    message: str
    object_name: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("message", self.message)


@dataclass(frozen=True, slots=True)
class MaskingInstruction:
    field_name: str
    strategy: MaskingStrategy
    reason: str

    def __post_init__(self) -> None:
        _require_non_empty("field_name", self.field_name)
        _require_non_empty("reason", self.reason)


def _empty_rule_hits() -> list[RuleHit]:
    return []


def _empty_masking_plan() -> list[MaskingInstruction]:
    return []


@dataclass(frozen=True, slots=True)
class GuardrailDecisionV2:
    decision: GuardrailDecisionStatus
    rewritten_sql: str | None
    sql_hash: str
    rule_hits: list[RuleHit] = field(default_factory=_empty_rule_hits)
    masking_plan: list[MaskingInstruction] = field(default_factory=_empty_masking_plan)
    error: ErrorPayloadV2 | None = None

    def __post_init__(self) -> None:
        _require_non_empty("sql_hash", self.sql_hash)
        if self.decision is GuardrailDecisionStatus.ALLOW:
            if self.rewritten_sql is None or not self.rewritten_sql.strip():
                raise ValueError("allowed guardrail decision must include rewritten_sql")
            if self.error is not None:
                raise ValueError("allowed guardrail decision must not include error")
        if self.decision is GuardrailDecisionStatus.DENY:
            if self.rewritten_sql is not None:
                raise ValueError("denied guardrail decision must not include rewritten_sql")
            if self.error is None:
                raise ValueError("denied guardrail decision must include error")


def _require_non_empty(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_sql_text(sql_text: str) -> None:
    sql_length = len(sql_text.strip())
    if sql_length < 1 or sql_length > MAX_SQL_TEXT_LENGTH:
        raise ValueError("sql_text length must be between 1 and 20000 characters")
