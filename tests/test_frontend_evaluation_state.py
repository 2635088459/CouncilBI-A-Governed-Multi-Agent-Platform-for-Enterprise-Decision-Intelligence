from typing import Any, Mapping

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import EvaluationRunViewModel, FrontendUserContext
from chatbi.frontend.evaluation_state import (
    EvaluationPageStore,
    ReleaseGateStatus,
)


class FakeEvaluationApiClient:
    def __init__(self, release_gate_passed: bool = True) -> None:
        self.release_gate_passed = release_gate_passed
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def run_evaluation(
        self,
        context: FrontendUserContext,
        eval_suite_id: str,
        questions: tuple[str, ...] = (),
    ) -> EvaluationRunViewModel:
        self.calls.append((eval_suite_id, questions))
        failed_cases = 0 if self.release_gate_passed else 1
        return EvaluationRunViewModel(
            eval_run_id="eval_001",
            eval_suite_id=eval_suite_id,
            total_cases=2,
            passed_cases=2 - failed_cases,
            failed_cases=failed_cases,
            overall_score=1.0 if self.release_gate_passed else 0.5,
            average_confidence=0.9,
            metric_breakdown={
                "sql_safety": 1.0 if self.release_gate_passed else 0.0,
                "answer_success": 1.0 if self.release_gate_passed else 0.5,
            },
            failed_cases_detail=(
                (_failed_case(),)
                if not self.release_gate_passed
                else ()
            ),
            release_gate_passed=self.release_gate_passed,
        )


class ErrorEvaluationApiClient(FakeEvaluationApiClient):
    def run_evaluation(
        self,
        context: FrontendUserContext,
        eval_suite_id: str,
        questions: tuple[str, ...] = (),
    ) -> EvaluationRunViewModel:
        raise ValueError("Evaluation API failed.")


def test_run_current_suite_stores_passed_report() -> None:
    api_client = FakeEvaluationApiClient(release_gate_passed=True)
    store = EvaluationPageStore(context=_context(), api_client=api_client)

    state = store.run_current_suite()

    assert state.is_running is False
    assert state.error_message is None
    assert state.latest_report is not None
    assert state.latest_report.eval_run_id == "eval_001"
    assert state.release_gate_status is ReleaseGateStatus.PASSED
    assert api_client.calls == [("backend_api_smoke", ())]


def test_run_current_suite_stores_failed_gate_report() -> None:
    store = EvaluationPageStore(
        context=_context(),
        api_client=FakeEvaluationApiClient(release_gate_passed=False),
    )

    state = store.run_current_suite()

    assert state.latest_report is not None
    assert state.latest_report.failed_cases == 1
    assert state.latest_report.failed_cases_detail[0]["question"] == "DROP TABLE orders"
    assert state.release_gate_status is ReleaseGateStatus.FAILED


def test_set_questions_trims_empty_questions_before_run() -> None:
    api_client = FakeEvaluationApiClient()
    store = EvaluationPageStore(context=_context(), api_client=api_client)

    store.set_eval_suite_id(" frontend_smoke ")
    store.set_questions((" Show revenue trend. ", "", "  DROP TABLE orders  "))
    state = store.run_current_suite()

    assert state.eval_suite_id == "frontend_smoke"
    assert state.questions == ("Show revenue trend.", "DROP TABLE orders")
    assert api_client.calls == [
        ("frontend_smoke", ("Show revenue trend.", "DROP TABLE orders"))
    ]


def test_set_eval_suite_id_rejects_empty_value() -> None:
    store = EvaluationPageStore(
        context=_context(),
        api_client=FakeEvaluationApiClient(),
    )

    try:
        store.set_eval_suite_id("  ")
    except ValueError as exc:
        assert str(exc) == "Evaluation suite id is required."
    else:
        raise AssertionError("Expected empty eval suite id to fail.")


def test_run_current_suite_records_error_without_report() -> None:
    store = EvaluationPageStore(context=_context(), api_client=ErrorEvaluationApiClient())

    state = store.run_current_suite()

    assert state.is_running is False
    assert state.latest_report is None
    assert state.error_message == "Evaluation API failed."
    assert state.release_gate_status is ReleaseGateStatus.NOT_RUN


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.ANALYST,
        bearer_token="test-token",
    )


def _failed_case() -> Mapping[str, Any]:
    return {
        "question": "DROP TABLE orders",
        "trace_id": "trc_failed",
        "passed": False,
        "score": 0.0,
        "confidence": 0.0,
        "error_code": "SQL_GUARDRAIL_BLOCKED",
    }
