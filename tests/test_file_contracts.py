from datetime import datetime, timezone

import pytest

from chatbi.core.contracts import TableResult
from chatbi.files import (
    ChunkUrl,
    FederatedQueryAgentOutput,
    FileDataAgentInput,
    FileDataAgentOutput,
    FilePreviewResponse,
    FileShareRecord,
    FileUploadInitRequest,
    FileUploadInitResponse,
    PostgresQueryContext,
    UserUploadedFile,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _structured_file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_abc123",
        org_id="org_1",
        user_id="user_1",
        original_name="revenue.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=1024,
        storage_key="org_1/user_1/ufile_abc123/revenue.csv",
        content_hash="hash_abc123",
        status="ready",
        scope="user",
        file_group_id="fgrp_1",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}]},
        row_count=10,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def test_user_uploaded_file_accepts_a_ready_structured_record() -> None:
    file_record = _structured_file()

    assert file_record.status == "ready"
    assert file_record.schema_json is not None


def test_user_uploaded_file_rejects_bad_file_id_prefix() -> None:
    with pytest.raises(ValueError, match="file_id"):
        _structured_file(file_id="not_prefixed")


def test_user_uploaded_file_requires_session_id_for_session_scope() -> None:
    with pytest.raises(ValueError, match="session_id"):
        _structured_file(scope="session", session_id=None)


def test_user_uploaded_file_requires_schema_json_once_ready() -> None:
    with pytest.raises(ValueError, match="schema_json"):
        _structured_file(schema_json=None)


def test_user_uploaded_file_rejects_schema_json_for_unstructured_files() -> None:
    with pytest.raises(ValueError, match="schema_json"):
        _structured_file(
            file_type="unstructured",
            status="ready",
            schema_json={"columns": []},
            row_count=None,
            chunk_count=3,
        )


def test_user_uploaded_file_requires_error_reason_when_failed() -> None:
    with pytest.raises(ValueError, match="error_reason"):
        _structured_file(status="failed", schema_json=None, row_count=None, error_reason=None)


def test_user_uploaded_file_requires_content_hash() -> None:
    # Spec FV10.3 §6.1: content_hash is required (SHA-256 of the raw bytes).
    with pytest.raises(ValueError, match="content_hash"):
        _structured_file(content_hash="")


def test_user_uploaded_file_defaults_archived_at_to_none() -> None:
    # Spec FV10.3 §3: archived_at is a new field, distinct from deleted_at.
    file_record = _structured_file()

    assert file_record.archived_at is None
    assert file_record.deleted_at is None


def test_file_upload_init_request_requires_session_id_for_session_scope() -> None:
    with pytest.raises(ValueError, match="session_id"):
        FileUploadInitRequest(
            original_name="revenue.csv",
            file_size_bytes=1024,
            mime_type="text/csv",
            scope="session",
        )


def test_file_upload_init_response_requires_url_per_chunk() -> None:
    with pytest.raises(ValueError, match="presigned_urls"):
        FileUploadInitResponse(
            upload_id="upl_1",
            chunk_size_bytes=5_000_000,
            chunk_count=2,
            presigned_urls=(ChunkUrl(chunk_index=0, url="https://example.test/0"),),
        )


def test_file_share_record_rejects_self_share() -> None:
    with pytest.raises(ValueError, match="differ"):
        FileShareRecord(
            share_id="shr_1",
            file_id="ufile_abc123",
            granted_by="user_1",
            granted_to="user_1",
            created_at=_now(),
        )


def test_file_share_record_is_active_until_revoked() -> None:
    share = FileShareRecord(
        share_id="shr_1",
        file_id="ufile_abc123",
        granted_by="user_1",
        granted_to="user_2",
        created_at=_now(),
    )

    assert share.is_active
    assert not FileShareRecord(
        share_id="shr_1",
        file_id="ufile_abc123",
        granted_by="user_1",
        granted_to="user_2",
        created_at=_now(),
        revoked_at=_now(),
    ).is_active


def test_file_preview_response_rejects_mixed_variants() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FilePreviewResponse(
            file_id="ufile_abc123",
            columns=("month",),
            rows=({"month": "2026-01"},),
            total_row_count=1,
            chunks=("chunk one",),
            total_chunk_count=1,
        )


def test_file_preview_response_caps_structured_rows_at_50() -> None:
    rows = tuple({"month": str(i)} for i in range(51))
    with pytest.raises(ValueError, match="50"):
        FilePreviewResponse(
            file_id="ufile_abc123",
            columns=("month",),
            rows=rows,
            total_row_count=51,
        )


def test_file_data_agent_input_requires_at_least_one_file_id() -> None:
    with pytest.raises(ValueError, match="file_ids"):
        FileDataAgentInput(
            file_ids=(),
            user_id="user_1",
            question="what is total revenue?",
            role="analyst",
            trace_id="trc_1",
        )


def test_file_data_agent_output_rejects_table_result_when_blocked() -> None:
    with pytest.raises(ValueError, match="guardrail-blocked"):
        FileDataAgentOutput(
            file_ids_queried=("ufile_abc123",),
            guardrail_blocked=True,
            table_result=TableResult(columns=("a",), rows=({"a": 1},)),
        )


def test_postgres_query_context_requires_positive_max_rows() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        PostgresQueryContext(table_name="revenue", columns=("month",), max_rows=0)


def test_federated_query_agent_output_requires_reason_when_degraded() -> None:
    with pytest.raises(ValueError, match="degradation_reason"):
        FederatedQueryAgentOutput(degraded=True)
