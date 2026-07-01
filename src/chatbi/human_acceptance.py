"""Human acceptance review for the spec-10 release gate.

Machine gates answer "is it typed, tested, and safe enough?". Human acceptance
answers the last product question: "does one successful example make business
sense to a reviewer?".
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.release_gate import (
    ReleaseGateCheckName,
    ReleaseGateCheckResult,
    ReleaseGateReport,
    failed_check,
    passed_check,
)


@dataclass(frozen=True, slots=True)
class HumanAcceptanceExample:
    trace_id: str
    question: str
    answer_text: str
    sql_text: str

    def __post_init__(self) -> None:
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")
        if not self.question.strip():
            raise ValueError("question is required")
        if not self.answer_text.strip():
            raise ValueError("answer_text is required")
        if not self.sql_text.strip():
            raise ValueError("sql_text is required")


@dataclass(frozen=True, slots=True)
class HumanAcceptanceReview:
    reviewer: str
    example: HumanAcceptanceExample
    business_correct: bool
    usable_response: bool
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.reviewer.strip():
            raise ValueError("reviewer is required")

    @property
    def accepted(self) -> bool:
        return self.business_correct and self.usable_response


def human_acceptance_check(
    machine_report: ReleaseGateReport,
    review: HumanAcceptanceReview,
) -> ReleaseGateCheckResult:
    """Convert one human review into the release-gate check result."""

    if not machine_report.release_allowed:
        return failed_check(
            ReleaseGateCheckName.HUMAN_ACCEPTANCE,
            "Human acceptance cannot override failing machine gates.",
        )
    if review.accepted:
        return passed_check(
            ReleaseGateCheckName.HUMAN_ACCEPTANCE,
            f"Human acceptance passed for {review.example.trace_id}.",
        )
    return failed_check(
        ReleaseGateCheckName.HUMAN_ACCEPTANCE,
        _human_acceptance_failure_message(review),
    )


def _human_acceptance_failure_message(review: HumanAcceptanceReview) -> str:
    reasons: list[str] = []
    if not review.business_correct:
        reasons.append("business correctness was not accepted")
    if not review.usable_response:
        reasons.append("response usability was not accepted")
    reason_text = "; ".join(reasons) or "review was not accepted"
    if review.notes.strip():
        return f"Human acceptance failed: {reason_text}. Notes: {review.notes.strip()}"
    return f"Human acceptance failed: {reason_text}."
