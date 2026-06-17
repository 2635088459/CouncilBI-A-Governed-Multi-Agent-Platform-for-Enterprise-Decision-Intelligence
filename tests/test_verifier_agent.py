import pytest

from chatbi.agents.verifier_agent import VerifierAgentRunner


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
