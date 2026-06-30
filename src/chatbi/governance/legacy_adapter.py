"""Adapters between v2 guardrail contracts and legacy guardrail inputs."""

from __future__ import annotations

from chatbi.core.contracts import Locale, QueryRequest, UserRole
from chatbi.governance.contracts import GuardrailRequestV2


LEGACY_GUARDRAIL_SESSION_ID = "s_guardrail_v2"
LEGACY_GUARDRAIL_QUESTION = "SQL guardrail v2 check."


class GuardrailLegacyRequestAdapter:
    """Convert v2 guardrail requests into the legacy QueryRequest contract."""

    def to_query_request(self, request: GuardrailRequestV2) -> QueryRequest:
        return QueryRequest(
            user_id=request.user_id,
            session_id=LEGACY_GUARDRAIL_SESSION_ID,
            question=LEGACY_GUARDRAIL_QUESTION,
            locale=Locale.EN,
            role=UserRole(request.role),
        )
