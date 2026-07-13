from chatbi.core.contracts import EvidenceItem, TableResult
from chatbi.files import FederatedQueryAgentOutput, FileDataAgentOutput
from chatbi.orchestration import ResultMerger


def _table(value: str) -> TableResult:
    return TableResult(columns=("value",), rows=({"value": value},))


def test_merge_tags_file_only_table_result_as_file() -> None:
    file_output = FileDataAgentOutput(
        file_ids_queried=("ufile_a",),
        guardrail_blocked=False,
        table_result=_table("file-data"),
    )

    context = ResultMerger().merge(file_output=file_output)

    assert len(context.table_results) == 1
    assert context.table_results[0].source == "file"
    assert context.table_results[0].file_ids == ("ufile_a",)
    assert context.table_results[0].table_result.rows == ({"value": "file-data"},)


def test_merge_tags_file_and_sql_results_as_two_separate_entries() -> None:
    file_output = FileDataAgentOutput(
        file_ids_queried=("ufile_a",),
        guardrail_blocked=False,
        table_result=_table("file-data"),
    )
    sql_table_result = _table("sql-data")

    context = ResultMerger().merge(file_output=file_output, sql_table_result=sql_table_result)

    assert len(context.table_results) == 2
    sources = {entry.source for entry in context.table_results}
    assert sources == {"file", "database"}
    # Python never JOINs the two tables; each keeps its own independent rows.
    file_entry = next(entry for entry in context.table_results if entry.source == "file")
    db_entry = next(entry for entry in context.table_results if entry.source == "database")
    assert file_entry.table_result.rows == ({"value": "file-data"},)
    assert db_entry.table_result.rows == ({"value": "sql-data"},)


def test_merge_returns_empty_table_results_when_nothing_ran() -> None:
    context = ResultMerger().merge()

    assert context.table_results == ()
    assert context.evidence_items == ()


def test_merge_prefers_federated_output_over_separate_file_and_sql_results() -> None:
    federated_output = FederatedQueryAgentOutput(degraded=False, table_result=_table("federated-data"))
    file_output = FileDataAgentOutput(
        file_ids_queried=("ufile_a",),
        guardrail_blocked=False,
        table_result=_table("file-data"),
    )

    context = ResultMerger().merge(
        file_output=file_output,
        sql_table_result=_table("sql-data"),
        federated_output=federated_output,
    )

    assert len(context.table_results) == 1
    assert context.table_results[0].source == "federated"
    assert context.table_results[0].table_result.rows == ({"value": "federated-data"},)


def test_merge_tags_degraded_federated_output_as_file_using_file_output_ids() -> None:
    federated_output = FederatedQueryAgentOutput(
        degraded=True,
        degradation_reason="POSTGRES_ROW_CAP_EXCEEDED",
        table_result=_table("file-only-fallback"),
    )
    file_output = FileDataAgentOutput(
        file_ids_queried=("ufile_a", "ufile_b"),
        guardrail_blocked=False,
        table_result=_table("file-only-fallback"),
    )

    context = ResultMerger().merge(file_output=file_output, federated_output=federated_output)

    assert len(context.table_results) == 1
    assert context.table_results[0].source == "file"
    assert context.table_results[0].file_ids == ("ufile_a", "ufile_b")


def test_merge_tags_uploaded_and_knowledge_base_evidence_separately() -> None:
    uploaded_item = EvidenceItem(
        source_id="ufile_doc1",
        title="playbook.pdf",
        citation_anchor="ufile_doc1#0",
        snippet="Escalate P1 incidents within 15 minutes.",
    )
    knowledge_base_item = EvidenceItem(
        source_id="doc_official",
        title="Incident runbook",
        citation_anchor="doc_official#3",
        snippet="Standard escalation policy.",
    )

    context = ResultMerger().merge(
        uploaded_file_evidence=(uploaded_item,),
        knowledge_base_evidence=(knowledge_base_item,),
    )

    assert len(context.evidence_items) == 2
    uploaded = next(item for item in context.evidence_items if item.evidence.source_id == "ufile_doc1")
    knowledge_base = next(
        item for item in context.evidence_items if item.evidence.source_id == "doc_official"
    )
    assert uploaded.is_uploaded_file is True
    assert knowledge_base.is_uploaded_file is False
