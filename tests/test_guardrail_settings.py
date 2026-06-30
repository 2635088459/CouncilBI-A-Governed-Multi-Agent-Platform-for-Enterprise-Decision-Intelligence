import pytest

from chatbi.core.contracts import (
    GuardrailDecision,
    Locale,
    QueryRequest,
    UserRole,
)
from chatbi.governance import (
    DEFAULT_GUARDRAIL_MAX_ROWS,
    DEFAULT_GUARDRAIL_TIMEOUT_MS,
    GUARDRAIL_MAX_ROWS_ENV,
    GUARDRAIL_TIMEOUT_MS_ENV,
    GuardrailDecisionStatus,
    GuardrailRequestV2,
    GuardrailSettings,
    SimpleSqlGuardrail,
    SimpleSqlGuardrailV2,
    load_guardrail_settings,
)


def make_legacy_request() -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question="Show revenue trend.",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def test_guardrail_settings_defaults_match_spec_safe_limits() -> None:
    settings = GuardrailSettings()

    assert settings.max_rows == DEFAULT_GUARDRAIL_MAX_ROWS
    assert settings.timeout_ms == DEFAULT_GUARDRAIL_TIMEOUT_MS


def test_load_guardrail_settings_reads_environment_values() -> None:
    settings = load_guardrail_settings(
        {
            GUARDRAIL_MAX_ROWS_ENV: "50",
            GUARDRAIL_TIMEOUT_MS_ENV: "1500",
        }
    )

    assert settings.max_rows == 50
    assert settings.timeout_ms == 1500


def test_load_guardrail_settings_treats_blank_values_as_defaults() -> None:
    settings = load_guardrail_settings(
        {
            GUARDRAIL_MAX_ROWS_ENV: " ",
            GUARDRAIL_TIMEOUT_MS_ENV: "",
        }
    )

    assert settings.max_rows == DEFAULT_GUARDRAIL_MAX_ROWS
    assert settings.timeout_ms == DEFAULT_GUARDRAIL_TIMEOUT_MS


@pytest.mark.parametrize(
    "env",
    (
        {GUARDRAIL_MAX_ROWS_ENV: "0"},
        {GUARDRAIL_MAX_ROWS_ENV: "abc"},
        {GUARDRAIL_TIMEOUT_MS_ENV: "0"},
        {GUARDRAIL_TIMEOUT_MS_ENV: "abc"},
    ),
)
def test_load_guardrail_settings_rejects_invalid_positive_ints(
    env: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        load_guardrail_settings(env)


def test_simple_guardrail_uses_configured_max_rows() -> None:
    guardrail = SimpleSqlGuardrail(settings=GuardrailSettings(max_rows=25))

    result = guardrail.check(
        "SELECT month, revenue FROM revenue_by_month",
        make_legacy_request(),
        "tr_12345678",
    )

    assert result.decision is GuardrailDecision.ALLOW
    assert result.safe_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 25"


def test_simple_guardrail_uses_configured_timeout() -> None:
    guardrail = SimpleSqlGuardrail(settings=GuardrailSettings(timeout_ms=500))

    result = guardrail.check_timeout(
        elapsed_ms=501,
        sql_text="SELECT month, revenue FROM revenue_by_month",
        request=make_legacy_request(),
        trace_id="tr_12345678",
    )

    assert result is not None
    assert result.decision is GuardrailDecision.DENY
    assert result.message == "Query exceeded timeout of 500ms after running for 501ms."


def test_v2_guardrail_uses_configured_max_rows() -> None:
    decision = SimpleSqlGuardrailV2(settings=GuardrailSettings(max_rows=25)).check(
        GuardrailRequestV2(
            trace_id="tr_12345678",
            user_id="u_001",
            role="business_user",
            sql_text="SELECT month, revenue FROM revenue_by_month",
            semantic_version_id="sem_v1",
        )
    )

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert decision.rewritten_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 25"
