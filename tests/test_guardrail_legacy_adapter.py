from chatbi.core.contracts import Locale, UserRole
from chatbi.governance import (
    GuardrailLegacyRequestAdapter,
    GuardrailRequestV2,
    LEGACY_GUARDRAIL_QUESTION,
    LEGACY_GUARDRAIL_SESSION_ID,
)


def test_guardrail_legacy_request_adapter_converts_v2_request() -> None:
    request = GuardrailRequestV2(
        trace_id="tr_12345678",
        user_id="u_001",
        role="analyst",
        sql_text="SELECT month, revenue FROM revenue_by_month",
        semantic_version_id="sem_v1",
    )

    legacy_request = GuardrailLegacyRequestAdapter().to_query_request(request)

    assert legacy_request.user_id == "u_001"
    assert legacy_request.session_id == LEGACY_GUARDRAIL_SESSION_ID
    assert legacy_request.question == LEGACY_GUARDRAIL_QUESTION
    assert legacy_request.locale is Locale.EN
    assert legacy_request.role is UserRole.ANALYST


def test_guardrail_legacy_request_adapter_preserves_admin_role() -> None:
    request = GuardrailRequestV2(
        trace_id="tr_12345678",
        user_id="u_admin",
        role="admin",
        sql_text="SELECT * FROM orders",
        semantic_version_id="sem_v1",
    )

    legacy_request = GuardrailLegacyRequestAdapter().to_query_request(request)

    assert legacy_request.role is UserRole.ADMIN
