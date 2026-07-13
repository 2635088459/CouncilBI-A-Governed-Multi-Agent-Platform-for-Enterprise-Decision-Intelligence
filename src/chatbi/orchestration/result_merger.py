"""ResultMerger: FR-FV10-024/025 cross-data-source tagging for the LLM synthesizer.

See system_design/final-version/.../10-user-file-upload-and-hybrid-analysis
section 6.3, "ResultMerger 策略":

- FileDataAgent and the SQL agent both return a table: pass both tables to
  the LLM under separate labels; the LLM narrates the comparison, Python
  never JOINs them.
- Only FileDataAgent returns data: answer from the file data alone.
- FederatedQueryAgent ran instead of the two independent agents
  (FR-FV10-020): its single table supersedes both, tagged ``federated``
  (or ``file`` if it degraded to a file-only answer, per FR-FV10-022).
- RAG evidence is passed alongside table data, each item tagged with
  whether it came from a user upload (FR-FV10-025's "📎 已上传" marker) or
  the shared knowledge base.

This module does not execute SQL, call an LLM, or narrate anything itself —
it only shapes whichever agent outputs already ran into one tagged context.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chatbi.core.contracts import EvidenceItem, TableResult
from chatbi.files.contracts import (
    FederatedQueryAgentOutput,
    FileDataAgentOutput,
    SourcedEvidenceItem,
    SourcedTableResult,
)


def _empty_table_results() -> tuple[SourcedTableResult, ...]:
    return ()


def _empty_evidence_items() -> tuple[SourcedEvidenceItem, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class MergedResultContext:
    """The unified, tagged context handed to the LLM answer synthesizer."""

    table_results: tuple[SourcedTableResult, ...] = field(default_factory=_empty_table_results)
    evidence_items: tuple[SourcedEvidenceItem, ...] = field(default_factory=_empty_evidence_items)


class ResultMerger:
    """Tag and collect whichever agent outputs ran for one chat query."""

    def merge(
        self,
        *,
        file_output: FileDataAgentOutput | None = None,
        sql_table_result: TableResult | None = None,
        federated_output: FederatedQueryAgentOutput | None = None,
        uploaded_file_evidence: tuple[EvidenceItem, ...] = (),
        knowledge_base_evidence: tuple[EvidenceItem, ...] = (),
    ) -> MergedResultContext:
        table_results = self._merge_table_results(file_output, sql_table_result, federated_output)
        evidence_items = self._tag_evidence(uploaded_file_evidence, knowledge_base_evidence)
        return MergedResultContext(table_results=table_results, evidence_items=evidence_items)

    def _merge_table_results(
        self,
        file_output: FileDataAgentOutput | None,
        sql_table_result: TableResult | None,
        federated_output: FederatedQueryAgentOutput | None,
    ) -> tuple[SourcedTableResult, ...]:
        if federated_output is not None:
            return self._table_results_from_federated(federated_output, file_output)

        table_results: list[SourcedTableResult] = []
        if file_output is not None and file_output.table_result is not None:
            table_results.append(
                SourcedTableResult(
                    table_result=file_output.table_result,
                    source="file",
                    file_ids=file_output.file_ids_queried,
                )
            )
        if sql_table_result is not None:
            table_results.append(SourcedTableResult(table_result=sql_table_result, source="database"))
        return tuple(table_results)

    def _table_results_from_federated(
        self,
        federated_output: FederatedQueryAgentOutput,
        file_output: FileDataAgentOutput | None,
    ) -> tuple[SourcedTableResult, ...]:
        if federated_output.table_result is None:
            return ()
        if not federated_output.degraded:
            return (SourcedTableResult(table_result=federated_output.table_result, source="federated"),)

        # NFR-FV10-007/FR-FV10-022: a degraded federated answer is really
        # just the file side, so it is tagged "file" rather than
        # "federated". file_ids come from file_output when the caller has
        # it (FederatedQueryAgentOutput itself does not carry file_ids).
        file_ids = file_output.file_ids_queried if file_output is not None else ()
        return (
            SourcedTableResult(
                table_result=federated_output.table_result,
                source="file",
                file_ids=file_ids,
            ),
        )

    def _tag_evidence(
        self,
        uploaded_file_evidence: tuple[EvidenceItem, ...],
        knowledge_base_evidence: tuple[EvidenceItem, ...],
    ) -> tuple[SourcedEvidenceItem, ...]:
        return tuple(
            SourcedEvidenceItem(evidence=item, is_uploaded_file=True) for item in uploaded_file_evidence
        ) + tuple(
            SourcedEvidenceItem(evidence=item, is_uploaded_file=False)
            for item in knowledge_base_evidence
        )
