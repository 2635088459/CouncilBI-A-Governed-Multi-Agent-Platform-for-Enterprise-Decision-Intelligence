import pytest

from chatbi.agents.verifier_agent import VerifierAgentRunner
from chatbi.core.contracts import ErrorCode, WarningMessage


def test_verifier_agent_returns_verification_payload() -> None:
    runner = VerifierAgentRunner(
        verified=True,
        confidence=0.9,
        reason="Answer is consistent with SQL output.",
    )

    result = runner.run()

    assert result.payload == {
        "verified": True,
        "reason": "Answer is consistent with SQL output.",
        "findings": (),
    }
    assert result.confidence == 0.9


def test_verifier_agent_rejects_invalid_confidence() -> None:
    runner = VerifierAgentRunner(
        verified=False,
        confidence=1.1,
        reason="Invalid confidence.",
    )

    with pytest.raises(ValueError, match="confidence"):
        runner.run()


def test_verifier_agent_requires_reason() -> None:
    runner = VerifierAgentRunner(
        verified=False,
        confidence=0.4,
        reason=" ",
    )

    with pytest.raises(ValueError, match="reason"):
        runner.run()


def test_verifier_agent_flags_missing_sql_text() -> None:
    runner = VerifierAgentRunner(
        verified=True,
        confidence=0.9,
        reason="Baseline checks completed.",
        sql_text=" ",
    )

    result = runner.run()

    assert result.payload["verified"] is False
    assert result.payload["findings"] == ("SQL text is missing.",)
    assert result.confidence == 0.7


def test_verifier_agent_flags_missing_required_fields() -> None:
    runner = VerifierAgentRunner(
        verified=True,
        confidence=0.9,
        reason="Required fields were checked.",
        required_fields={
            "answer_text": "Revenue is ready.",
            "table_result": None,
            "trace_id": "tr_12345678",
        },
    )

    result = runner.run()

    assert result.payload["verified"] is False
    assert result.payload["findings"] == ("Required answer field(s) missing: table_result.",)
    assert result.confidence == 0.7


def test_verifier_agent_flags_upstream_warnings() -> None:
    runner = VerifierAgentRunner(
        verified=True,
        confidence=0.9,
        reason="Upstream branches were checked.",
        warnings=(
            WarningMessage(
                code=ErrorCode.RAG_UNAVAILABLE,
                message="RAG evidence was unavailable.",
            ),
        ),
    )

    result = runner.run()

    assert result.payload["verified"] is False
    assert result.payload["findings"] == ("Upstream warning(s) present: RAG_UNAVAILABLE.",)
    assert result.confidence == 0.7
