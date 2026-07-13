from dataclasses import replace

from chatbi.core.contracts import ErrorCode, EvidenceItem, QueryAnswer, TableResult
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


def test_answer_assembly_verifier_accepts_evidence_only_grounding() -> None:
    # FR-FV10-060: a document-only answer has no SQL step planned — empty
    # sql_text/table_result is valid as long as evidence_list is non-empty.
    answer = replace(
        _answer(),
        sql_text="",
        table_result=TableResult(columns=(), rows=()),
        evidence_list=(
            EvidenceItem(
                source_id="doc_pricing",
                title="Pricing onepager",
                citation_anchor="doc_pricing#chunk-1",
                snippet="Team tier is $49/seat/month.",
            ),
        ),
    )

    verified = AnswerAssemblyVerifier().verify(answer)

    assert verified == answer
    assert verified.warnings == ()
    assert verified.confidence == answer.confidence


def test_answer_assembly_verifier_rejects_answer_with_neither_sql_nor_evidence() -> None:
    # An answer grounded in nothing at all is still an error, evidence-only
    # grounding is an alternative to SQL grounding, not a blanket exemption.
    answer = replace(
        _answer(),
        sql_text="",
        table_result=TableResult(columns=(), rows=()),
    )

    verified = AnswerAssemblyVerifier().verify(answer)

    assert verified.warnings[-1].code is ErrorCode.VERIFICATION_FAILED
    assert "sql_text is required" in verified.warnings[-1].message
    assert "table_result.columns is required" in verified.warnings[-1].message
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
