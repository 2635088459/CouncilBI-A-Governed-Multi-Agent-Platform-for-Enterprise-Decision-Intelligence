import pytest

from chatbi.agents.sql_agent import SqlAgentRunner
from chatbi.core.contracts import ErrorCode, Locale, QueryRequest, UserRole, new_trace_id
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail
from chatbi.orchestration.executor import AgentStepError


def make_request(question: str = "Show revenue trend.") -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question=question,
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def test_sql_agent_returns_safe_sql_for_allowed_select() -> None:
    runner = SqlAgentRunner(
        sql_candidate="SELECT month, revenue FROM revenue_by_month",
        request=make_request(),
        trace_id=new_trace_id(),
        guardrail=SimpleSqlGuardrail(),
    )

    result = runner.run()

    assert result.payload == {"safe_sql": "SELECT month, revenue FROM revenue_by_month LIMIT 100"}
    assert result.confidence == 0.9


def test_sql_agent_raises_structured_error_for_denied_sql() -> None:
    runner = SqlAgentRunner(
        sql_candidate="DROP TABLE orders",
        request=make_request("DROP TABLE orders"),
        trace_id=new_trace_id(),
        guardrail=SimpleSqlGuardrail(),
    )

    with pytest.raises(AgentStepError) as exc_info:
        runner.run()

    assert exc_info.value.error_code is ErrorCode.SQL_DENY_STATEMENT
