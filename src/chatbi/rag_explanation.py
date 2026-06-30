"""Evidence-cited explanation helpers for RAG v2.

Retrieval answers the question "which chunks are relevant?" This module handles
the next question: "can we make a claim from those chunks, and did we cite it?"
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.rag import EvidenceItem, EvidenceSearchResult, RagWarningCode


@dataclass(frozen=True, slots=True)
class DocumentSupportedClaim:
    text: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("claim text is required")
        if not self.evidence_ids:
            raise ValueError("document-supported claims must cite at least one evidence_id")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("evidence_ids must not contain empty values")


@dataclass(frozen=True, slots=True)
class RagExplanation:
    answer_text: str
    claims: tuple[DocumentSupportedClaim, ...]
    evidence_list: tuple[EvidenceItem, ...]
    warnings: tuple[RagWarningCode, ...]

    def __post_init__(self) -> None:
        if not self.answer_text.strip():
            raise ValueError("answer_text is required")
        _validate_claim_citations(self.claims, self.evidence_list)


def build_rag_explanation(
    search_result: EvidenceSearchResult,
    answer_intro: str = "I found document evidence for this answer.",
) -> RagExplanation:
    """Build a simple explanation where every claim cites returned evidence."""

    if not search_result.evidence_list:
        return RagExplanation(
            answer_text="No relevant evidence was found, so no document-supported claim was made.",
            claims=(),
            evidence_list=(),
            warnings=search_result.warnings or (RagWarningCode.NO_EVIDENCE,),
        )

    claims = tuple(
        DocumentSupportedClaim(
            text=f"{evidence.snippet} [{evidence.evidence_id}]",
            evidence_ids=(evidence.evidence_id,),
        )
        for evidence in search_result.evidence_list
    )
    cited_claims = " ".join(claim.text for claim in claims)
    return RagExplanation(
        answer_text=f"{answer_intro} {cited_claims}",
        claims=claims,
        evidence_list=search_result.evidence_list,
        warnings=search_result.warnings,
    )


def validate_rag_explanation(explanation: RagExplanation) -> None:
    """Raise ValueError when an explanation violates citation rules."""

    _validate_claim_citations(explanation.claims, explanation.evidence_list)


def _validate_claim_citations(
    claims: tuple[DocumentSupportedClaim, ...],
    evidence_list: tuple[EvidenceItem, ...],
) -> None:
    returned_evidence_ids = {evidence.evidence_id for evidence in evidence_list}
    for claim in claims:
        missing_ids = tuple(
            evidence_id
            for evidence_id in claim.evidence_ids
            if evidence_id not in returned_evidence_ids
        )
        if missing_ids:
            missing_text = ", ".join(missing_ids)
            raise ValueError(f"claim cites evidence_id not returned by retrieval: {missing_text}")
