import os
from uuid import uuid4

import pytest

from chatbi.governance import (
    GuardrailDecisionStatus,
    GuardrailRequestV2,
    SimpleSqlGuardrailV2,
    postgres_guardrail_audit_log_v2_from_psycopg,
)
from chatbi.history.request_metadata import connect_psycopg


def test_postgres_guardrail_audit_live_writes_allow_and_deny_decisions() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for live guardrail audit integration.")

    connection = connect_psycopg(database_url)
    audit_log = postgres_guardrail_audit_log_v2_from_psycopg(connection)
    audit_log.initialize_schema()
    guardrail = SimpleSqlGuardrailV2(audit_log=audit_log)
    allow_trace_id = f"tr_guardrail_allow_{uuid4().hex[:16]}"
    deny_trace_id = f"tr_guardrail_deny_{uuid4().hex[:16]}"

    allow_decision = guardrail.check(
        GuardrailRequestV2(
            trace_id=allow_trace_id,
            user_id="u_live",
            role="business_user",
            sql_text="SELECT month, revenue FROM revenue_by_month",
            semantic_version_id="sem_v1",
        )
    )
    deny_decision = guardrail.check(
        GuardrailRequestV2(
            trace_id=deny_trace_id,
            user_id="u_live",
            role="business_user",
            sql_text="DROP TABLE orders",
            semantic_version_id="sem_v1",
        )
    )

    allow_record = audit_log.get_v2(allow_trace_id)
    deny_record = audit_log.get_v2(deny_trace_id)
    connection.close()

    assert allow_decision.decision is GuardrailDecisionStatus.ALLOW
    assert deny_decision.decision is GuardrailDecisionStatus.DENY
    assert allow_record is not None
    assert allow_record.trace_id == allow_trace_id
    assert allow_record.sql_hash == allow_decision.sql_hash
    assert allow_record.decision is GuardrailDecisionStatus.ALLOW
    assert deny_record is not None
    assert deny_record.trace_id == deny_trace_id
    assert deny_record.sql_hash == deny_decision.sql_hash
    assert deny_record.decision is GuardrailDecisionStatus.DENY
    assert len(deny_record.rule_hits) >= 1
