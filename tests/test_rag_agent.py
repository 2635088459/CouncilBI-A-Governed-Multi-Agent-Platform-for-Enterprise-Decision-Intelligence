import pytest

from chatbi.agents.rag_agent import RagAgentRunner
from chatbi.core.contracts import EvidenceItem


def make_evidence_item(citation_anchor: str = "doc_001#p1") -> EvidenceItem:
    return EvidenceItem(
        source_id="doc_001",
        title="Campaign report",
        citation_anchor=citation_anchor,
        snippet="Revenue increased after campaign launch.",
    )


def test_rag_agent_returns_evidence_payload() -> None:
    evidence = (make_evidence_item(),)
    runner = RagAgentRunner(evidence_items=evidence)

    result = runner.run()

    assert result.payload == {
        "evidence_count": 1,
        "evidence_items": evidence,
    }
    assert result.confidence == 0.8


def test_rag_agent_requires_at_least_one_evidence_item() -> None:
    runner = RagAgentRunner(evidence_items=())

    with pytest.raises(ValueError, match="evidence item"):
        runner.run()


def test_rag_agent_requires_citation_anchor() -> None:
    runner = RagAgentRunner(evidence_items=(make_evidence_item(citation_anchor=" "),))

    with pytest.raises(ValueError, match="citation_anchor"):
        runner.run()
