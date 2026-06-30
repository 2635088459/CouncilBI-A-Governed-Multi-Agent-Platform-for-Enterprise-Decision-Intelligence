from chatbi.orchestration import (
    AgentStepInput,
    AgentStepName,
    AgentStepOutputStatus,
    OrchestrationRequest,
    UserContext,
    timed_out_agent_step_output,
)


def test_orchestration_package_exports_v2_contract_types() -> None:
    request = OrchestrationRequest(
        trace_id="tr_12345678",
        session_id="ses_12345678",
        user_context=UserContext(
            user_id="u_001",
            role="business_user",
            locale="en",
        ),
        question="Show revenue.",
        semantic_context={},
        deadline_ms=1_000,
    )
    step_input = AgentStepInput(
        trace_id=request.trace_id,
        step_name=AgentStepName.SQL,
        attempt=1,
        task_payload={},
        deadline_ms=500,
    )
    timeout_output = timed_out_agent_step_output()

    assert step_input.idempotency_key == "tr_12345678:sql:1"
    assert timeout_output.status is AgentStepOutputStatus.TIMED_OUT
