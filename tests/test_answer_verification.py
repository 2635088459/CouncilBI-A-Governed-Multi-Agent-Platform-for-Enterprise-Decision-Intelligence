from dataclasses import replace

from chatbi.core.contracts import ErrorCode, QueryAnswer, TableResult
from chatbi.orchestration.answer_verification import AnswerAssemblyVerifier


def test_answer_assembly_verifier_preserves_valid_answer() -> None:
    answer = _answer()

    verified = AnswerAssemblyVerifier().verify(answer)

    assert verified == answer


def test_answer_assembly_verifier_adds_warning_for_missing_required_field() -> None:
    answer = replace(_answer(), sql_text="")

    verified = AnswerAssemblyVerifier().verify(answer)

    assert verified.warnings[-1].code is ErrorCode.VERIFICATION_FAILED
    assert "sql_text is required" in verified.warnings[-1].message
    assert verified.confidence == 0.5


def _answer() -> QueryAnswer:
    return QueryAnswer(
        answer_text="Revenue trend is ready.",
        sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        table_result=TableResult(
            columns=("month", "revenue"),
            rows=({"month": "2026-01", "revenue": 1000},),
        ),
        trace_id="trc_answer_verification",
        confidence=0.9,
    )
