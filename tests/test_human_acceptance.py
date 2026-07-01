from chatbi.human_acceptance import (
    HumanAcceptanceExample,
    HumanAcceptanceReview,
    human_acceptance_check,
)
from chatbi.release_gate import (
    ReleaseGateCheckName,
    ReleaseGateReport,
    failed_check,
    passed_check,
)


def test_human_acceptance_passes_after_machine_gates_pass() -> None:
    review = HumanAcceptanceReview(
        reviewer="teacher",
        example=_example(),
        business_correct=True,
        usable_response=True,
        notes="Revenue answer matched the expected dashboard metric.",
    )

    result = human_acceptance_check(
        machine_report=_machine_report(passed=True),
        review=review,
    )

    assert result.name is ReleaseGateCheckName.HUMAN_ACCEPTANCE
    assert result.passed is True
    assert "trc_human_acceptance_example" in result.message


def test_human_acceptance_fails_when_business_review_rejects_example() -> None:
    review = HumanAcceptanceReview(
        reviewer="teacher",
        example=_example(),
        business_correct=False,
        usable_response=True,
        notes="The metric definition did not match finance's revenue definition.",
    )

    result = human_acceptance_check(
        machine_report=_machine_report(passed=True),
        review=review,
    )

    assert result.passed is False
    assert "business correctness was not accepted" in result.message
    assert "finance's revenue definition" in result.message


def test_human_acceptance_cannot_override_machine_gate_failure() -> None:
    review = HumanAcceptanceReview(
        reviewer="teacher",
        example=_example(),
        business_correct=True,
        usable_response=True,
    )

    result = human_acceptance_check(
        machine_report=_machine_report(passed=False),
        review=review,
    )

    assert result.passed is False
    assert result.message == "Human acceptance cannot override failing machine gates."


def test_human_acceptance_example_validates_required_fields() -> None:
    try:
        HumanAcceptanceExample(
            trace_id="bad_trace",
            question="Show revenue.",
            answer_text="Revenue is ready.",
            sql_text="SELECT revenue FROM orders",
        )
    except ValueError as exc:
        assert "trace_id" in str(exc)
    else:
        raise AssertionError("Expected invalid trace_id to raise ValueError.")


def _example() -> HumanAcceptanceExample:
    return HumanAcceptanceExample(
        trace_id="trc_human_acceptance_example",
        question="Show revenue trend.",
        answer_text="Revenue trend is ready.",
        sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
    )


def _machine_report(passed: bool) -> ReleaseGateReport:
    if passed:
        return ReleaseGateReport(
            checks=(
                passed_check(ReleaseGateCheckName.PYRIGHT),
                passed_check(ReleaseGateCheckName.PYTEST),
                passed_check(ReleaseGateCheckName.EVALUATION),
            )
        )
    return ReleaseGateReport(
        checks=(
            failed_check(ReleaseGateCheckName.PYRIGHT, "pyright failed."),
            passed_check(ReleaseGateCheckName.PYTEST),
            passed_check(ReleaseGateCheckName.EVALUATION),
        )
    )
