from chatbi.governance import (
    GuardrailDecisionAuditRecorder,
    GuardrailDecisionStatus,
    GuardrailDecisionV2,
    GuardrailLegacyAuditRecorder,
    GuardrailRequestV2,
    GuardrailRuleCode,
    InMemoryGuardrailAuditLog,
    InMemoryGuardrailAuditLogV2,
    RuleHit,
)
from chatbi.core.contracts import (
    ErrorCode,
    GuardrailDecision,
    GuardrailResult,
    Locale,
    QueryRequest,
    UserRole,
)


def make_legacy_request() -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question="Show revenue trend.",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def make_request() -> GuardrailRequestV2:
    return GuardrailRequestV2(
        trace_id="tr_12345678",
        user_id="u_001",
        role="analyst",
        sql_text="SELECT month, revenue FROM revenue_by_month",
        semantic_version_id="sem_v1",
    )


def make_decision() -> GuardrailDecisionV2:
    return GuardrailDecisionV2(
        decision=GuardrailDecisionStatus.ALLOW,
        rewritten_sql="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        sql_hash="abc123",
        rule_hits=[
            RuleHit(
                rule_code=GuardrailRuleCode.ROW_LIMIT_REWRITE,
                message="A row limit was added to the SQL.",
            )
        ],
    )


def test_guardrail_audit_recorder_writes_required_v2_audit_fields() -> None:
    audit_log = InMemoryGuardrailAuditLogV2()
    recorder = GuardrailDecisionAuditRecorder(
        audit_log=audit_log,
        clock=lambda: 11.25,
    )
    request = make_request()
    decision = make_decision()

    recorder.record(request=request, decision=decision, started_at=10.0)
    record = audit_log.get_v2(request.trace_id)

    assert record is not None
    assert record.trace_id == "tr_12345678"
    assert record.user_id == "u_001"
    assert record.role == "analyst"
    assert record.sql_hash == "abc123"
    assert record.decision is GuardrailDecisionStatus.ALLOW
    assert record.rule_hits == tuple(decision.rule_hits)
    assert record.latency_ms == 1250


def test_guardrail_audit_recorder_clamps_negative_latency_to_zero() -> None:
    audit_log = InMemoryGuardrailAuditLogV2()
    recorder = GuardrailDecisionAuditRecorder(
        audit_log=audit_log,
        clock=lambda: 9.0,
    )
    request = make_request()

    recorder.record(request=request, decision=make_decision(), started_at=10.0)
    record = audit_log.get_v2(request.trace_id)

    assert record is not None
    assert record.latency_ms == 0


def test_guardrail_audit_recorder_allows_missing_audit_log() -> None:
    recorder = GuardrailDecisionAuditRecorder(audit_log=None, clock=lambda: 11.0)

    recorder.record(request=make_request(), decision=make_decision(), started_at=10.0)


def test_guardrail_legacy_audit_recorder_writes_legacy_audit_record() -> None:
    audit_log = InMemoryGuardrailAuditLog()
    recorder = GuardrailLegacyAuditRecorder(audit_log)
    result = GuardrailResult(
        decision=GuardrailDecision.ALLOW,
        trace_id="tr_12345678",
        safe_sql="SELECT month, revenue FROM revenue_by_month LIMIT 100",
    )

    returned_result = recorder.record(
        original_sql="SELECT month, revenue FROM revenue_by_month",
        request=make_legacy_request(),
        result=result,
    )
    record = audit_log.get("tr_12345678")

    assert returned_result is result
    assert record is not None
    assert record.trace_id == "tr_12345678"
    assert record.user_id == "u_001"
    assert record.role is UserRole.BUSINESS_USER
    assert record.original_sql == "SELECT month, revenue FROM revenue_by_month"
    assert record.safe_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert record.decision is GuardrailDecision.ALLOW
    assert record.error_code is None


def test_guardrail_legacy_audit_recorder_writes_denial_record() -> None:
    audit_log = InMemoryGuardrailAuditLog()
    recorder = GuardrailLegacyAuditRecorder(audit_log)
    result = GuardrailResult(
        decision=GuardrailDecision.DENY,
        trace_id="tr_12345678",
        error_code=ErrorCode.SQL_DENY_STATEMENT,
        message="Only SELECT statements are allowed.",
    )

    recorder.record(
        original_sql="DROP TABLE orders",
        request=make_legacy_request(),
        result=result,
    )
    record = audit_log.get("tr_12345678")

    assert record is not None
    assert record.decision is GuardrailDecision.DENY
    assert record.original_sql == "DROP TABLE orders"
    assert record.safe_sql is None
    assert record.error_code is ErrorCode.SQL_DENY_STATEMENT
    assert record.message == "Only SELECT statements are allowed."


def test_guardrail_legacy_audit_recorder_allows_missing_audit_log() -> None:
    recorder = GuardrailLegacyAuditRecorder(audit_log=None)
    result = GuardrailResult(
        decision=GuardrailDecision.ALLOW,
        trace_id="tr_12345678",
        safe_sql="SELECT month, revenue FROM revenue_by_month LIMIT 100",
    )

    returned_result = recorder.record(
        original_sql="SELECT month, revenue FROM revenue_by_month",
        request=make_legacy_request(),
        result=result,
    )

    assert returned_result is result
