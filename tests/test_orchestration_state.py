import pytest

from chatbi.orchestration.contracts import AgentStepOutput, AgentStepOutputStatus
from chatbi.orchestration.executor import AgentRunResult
from chatbi.orchestration.state import (
    InMemoryOrchestrationStateStore,
    OrchestrationRequestState,
    RequestStateStage,
)


def test_state_store_saves_and_loads_successful_step_by_idempotency_key() -> None:
    store = InMemoryOrchestrationStateStore()
    run_result = AgentRunResult(payload={"safe_sql": "SELECT 1"}, confidence=0.9)
    step_output = AgentStepOutput(
        status=AgentStepOutputStatus.SUCCEEDED,
        result={"safe_sql": "SELECT 1"},
        confidence=0.9,
    )

    store.save_successful_step(
        idempotency_key="tr_12345678:sql:1",
        run_result=run_result,
        step_output=step_output,
    )
    stored = store.get_successful_step("tr_12345678:sql:1")

    assert stored is not None
    assert stored.trace_id == "tr_12345678"
    assert stored.run_result == run_result
    assert stored.step_output == step_output


def test_state_store_saves_request_state_by_trace_id() -> None:
    store = InMemoryOrchestrationStateStore()
    state = OrchestrationRequestState(
        trace_id="tr_12345678",
        stage=RequestStateStage.RUNNING,
        input_summary={"question_length": 12},
    )

    store.save_request_state(state)

    assert store.get_request_state("tr_12345678") == state


def test_failed_request_state_requires_error_payload() -> None:
    with pytest.raises(ValueError, match="error"):
        OrchestrationRequestState(
            trace_id="tr_12345678",
            stage=RequestStateStage.FAILED,
        )


def test_state_store_lists_successful_steps_for_one_trace() -> None:
    store = InMemoryOrchestrationStateStore()
    sql_result = AgentRunResult(payload={"safe_sql": "SELECT 1"}, confidence=0.9)
    verifier_result = AgentRunResult(payload={"verified": True}, confidence=0.8)
    output = AgentStepOutput(
        status=AgentStepOutputStatus.SUCCEEDED,
        result={},
        confidence=0.8,
    )

    store.save_successful_step("tr_12345678:sql:1", sql_result, output)
    store.save_successful_step("tr_12345678:verifier:1", verifier_result, output)
    store.save_successful_step("tr_other:sql:1", sql_result, output)

    stored = store.list_successful_steps("tr_12345678")

    assert tuple(step.idempotency_key for step in stored) == (
        "tr_12345678:sql:1",
        "tr_12345678:verifier:1",
    )


def test_state_store_does_not_list_timed_out_steps_as_successful() -> None:
    store = InMemoryOrchestrationStateStore()
    run_result = AgentRunResult(payload={"safe_sql": "SELECT 1"}, confidence=0.9)
    successful_output = AgentStepOutput(
        status=AgentStepOutputStatus.SUCCEEDED,
        result={"safe_sql": "SELECT 1"},
        confidence=0.9,
    )
    timeout_output = AgentStepOutput(
        status=AgentStepOutputStatus.TIMED_OUT,
        result=None,
        confidence=0.0,
        error={
            "code": "AGENT_TIMEOUT",
            "message": "Agent exceeded its deadline.",
            "retryable": True,
        },
    )

    store.save_successful_step("tr_12345678:sql:1", run_result, successful_output)
    store.save_step("tr_12345678:analytics:1", timeout_output)

    stored = store.list_successful_steps("tr_12345678")

    assert tuple(step.idempotency_key for step in stored) == ("tr_12345678:sql:1",)


def test_state_store_saves_timed_out_step_without_successful_result() -> None:
    store = InMemoryOrchestrationStateStore()
    timeout_output = AgentStepOutput(
        status=AgentStepOutputStatus.TIMED_OUT,
        result=None,
        confidence=0.0,
        error={
            "code": "AGENT_TIMEOUT",
            "message": "Agent exceeded its deadline.",
            "retryable": True,
        },
    )

    store.save_step("tr_12345678:sql:1", timeout_output)
    stored = store.get_step("tr_12345678:sql:1")

    assert stored is not None
    assert stored.run_result is None
    assert stored.step_output.status is AgentStepOutputStatus.TIMED_OUT
    stored_error = stored.step_output.error
    assert stored_error is not None
    assert stored_error["code"] == "AGENT_TIMEOUT"
    assert store.get_successful_step("tr_12345678:sql:1") is None
