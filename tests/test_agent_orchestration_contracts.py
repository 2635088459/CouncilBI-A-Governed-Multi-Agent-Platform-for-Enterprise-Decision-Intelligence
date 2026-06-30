import pytest

from chatbi.orchestration.contracts import (
    AgentStepInput,
    AgentStepName,
    AgentStepOutput,
    AgentStepOutputStatus,
    OrchestrationRequest,
    UserContext,
    timed_out_agent_step_output,
)


def test_orchestration_request_accepts_required_v2_fields() -> None:
    request = OrchestrationRequest(
        trace_id="tr_12345678",
        session_id="ses_12345678",
        user_context=UserContext(
            user_id="u_001",
            role="business_user",
            locale="en",
        ),
        question="Show revenue.",
        semantic_context={"dataset": "revenue"},
        deadline_ms=1_000,
    )

    assert request.trace_id == "tr_12345678"
    assert request.user_context.role == "business_user"
    assert request.semantic_context["dataset"] == "revenue"


def test_orchestration_request_rejects_question_outside_spec_length() -> None:
    with pytest.raises(ValueError, match="question length"):
        OrchestrationRequest(
            trace_id="tr_12345678",
            session_id="ses_12345678",
            user_context=UserContext(
                user_id="u_001",
                role="business_user",
                locale="en",
            ),
            question="",
            semantic_context={},
            deadline_ms=1_000,
        )


def test_agent_step_input_builds_spec_idempotency_key() -> None:
    step_input = AgentStepInput(
        trace_id="tr_12345678",
        step_name=AgentStepName.SQL,
        attempt=2,
        task_payload={"sql_candidate": "SELECT 1"},
        deadline_ms=500,
    )

    assert step_input.idempotency_key == "tr_12345678:sql:2"


def test_agent_step_input_rejects_attempt_above_retry_limit() -> None:
    with pytest.raises(ValueError, match="attempt"):
        AgentStepInput(
            trace_id="tr_12345678",
            step_name=AgentStepName.SQL,
            attempt=4,
            task_payload={},
            deadline_ms=500,
        )


def test_agent_step_output_accepts_success_payload() -> None:
    output = AgentStepOutput(
        status=AgentStepOutputStatus.SUCCEEDED,
        result={"safe_sql": "SELECT 1"},
        confidence=0.9,
        warnings=[],
        metrics={"duration_ms": 12},
        error=None,
    )

    assert output.result == {"safe_sql": "SELECT 1"}
    assert output.confidence == 0.9


def test_timed_out_agent_step_output_uses_required_timeout_error_code() -> None:
    output = timed_out_agent_step_output()

    assert output.status is AgentStepOutputStatus.TIMED_OUT
    assert output.error is not None
    assert output.error["code"] == "AGENT_TIMEOUT"
    assert output.error["retryable"] is True


def test_timed_out_status_requires_agent_timeout_error_code() -> None:
    with pytest.raises(ValueError, match="AGENT_TIMEOUT"):
        AgentStepOutput(
            status=AgentStepOutputStatus.TIMED_OUT,
            result=None,
            confidence=0.0,
            warnings=[],
            metrics={},
            error={
                "code": "OTHER_ERROR",
                "message": "wrong code",
                "retryable": True,
            },
        )
