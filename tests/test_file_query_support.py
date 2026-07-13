from datetime import datetime, timezone

from chatbi.agents.file_query_support import (
    question_references_any_attached_file,
    question_references_attached_file,
    split_file_ids_by_type,
)
from chatbi.files.contracts import UserUploadedFile


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _structured_file(file_id: str) -> UserUploadedFile:
    return UserUploadedFile(
        file_id=file_id,
        org_id="org_1",
        user_id="user_1",
        original_name=f"{file_id}.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=1024,
        storage_key=f"org_1/user_1/{file_id}/{file_id}.csv",
        content_hash=f"hash_{file_id}",
        status="ready",
        scope="user",
        file_group_id=f"fgrp_{file_id}",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}]},
        row_count=1,
    )


def _unstructured_file(file_id: str) -> UserUploadedFile:
    return UserUploadedFile(
        file_id=file_id,
        org_id="org_1",
        user_id="user_1",
        original_name=f"{file_id}.pdf",
        file_type="unstructured",
        mime_type="application/pdf",
        size_bytes=1024,
        storage_key=f"org_1/user_1/{file_id}/{file_id}.pdf",
        content_hash=f"hash_{file_id}",
        status="ready",
        scope="user",
        file_group_id=f"fgrp_{file_id}",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        schema_json=None,
        row_count=None,
        chunk_count=1,
    )


def test_split_file_ids_by_type_separates_a_mixed_selection_preserving_order() -> None:
    # TC-FV10-163
    files_by_id = {
        "ufile_a": _structured_file("ufile_a"),
        "ufile_b": _unstructured_file("ufile_b"),
        "ufile_c": _structured_file("ufile_c"),
    }

    structured, unstructured = split_file_ids_by_type(
        ("ufile_a", "ufile_b", "ufile_c"), files_by_id
    )

    assert structured == ("ufile_a", "ufile_c")
    assert unstructured == ("ufile_b",)


def test_split_file_ids_by_type_all_unstructured_returns_empty_structured_subset() -> None:
    # TC-FV10-164
    files_by_id = {
        "ufile_a": _unstructured_file("ufile_a"),
        "ufile_b": _unstructured_file("ufile_b"),
    }

    structured, unstructured = split_file_ids_by_type(("ufile_a", "ufile_b"), files_by_id)

    assert structured == ()
    assert unstructured == ("ufile_a", "ufile_b")


def _regional_sales_file() -> UserUploadedFile:
    # Matches the reported bug's real file: region/month/revenue/orders,
    # named with a quarter/year suffix that must not count as a relevance
    # signal on its own (see _GENERIC_DATE_TOKEN).
    return UserUploadedFile(
        file_id="ufile_regional",
        org_id="org_1",
        user_id="user_1",
        original_name="regional_sales_h1_2026.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=364,
        storage_key="org_1/user_1/ufile_regional/regional_sales_h1_2026.csv",
        content_hash="hash_regional",
        status="ready",
        scope="user",
        file_group_id="fgrp_regional",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        schema_json={
            "columns": [
                {"name": "region", "type": "VARCHAR"},
                {"name": "month", "type": "VARCHAR"},
                {"name": "revenue", "type": "BIGINT"},
                {"name": "orders", "type": "BIGINT"},
            ]
        },
        row_count=12,
    )


def test_question_references_attached_file_true_when_question_matches_a_column_name() -> None:
    file = _regional_sales_file()

    assert question_references_attached_file(
        "Summarize revenue by region for H1 2026.", file
    )


def test_question_references_attached_file_false_for_an_unrelated_question() -> None:
    # The exact reported bug: a question about support tickets/products has
    # nothing to do with a region/month/revenue/orders file.
    file = _regional_sales_file()

    assert not question_references_attached_file(
        "Compare total ticket count by product in H1 2026.", file
    )


def test_question_references_attached_file_ignores_generic_date_tokens_in_filename() -> None:
    # "h1"/"2026" appear in both the question and the filename by
    # coincidence, not because the question is actually about this file —
    # must not count as a relevance signal on its own.
    file = _regional_sales_file()

    assert not question_references_attached_file("What happened in H1 2026?", file)


def test_question_references_attached_file_true_for_a_generic_file_reference_hint() -> None:
    file = _regional_sales_file()

    assert question_references_attached_file(
        "Summarize the uploaded file and explain the trend.", file
    )


def test_question_references_attached_file_true_for_a_month_name_follow_up() -> None:
    # "And just June?" shares no literal value with a file whose month
    # column is formatted "2026-06" — this must still stay in the file
    # branch and let conversation-history resolution (Spec FV10.4) handle
    # it, not get rerouted by this gate the way "h1"/"2026" would be.
    file = _regional_sales_file()

    assert question_references_attached_file("What about just June?", file)


def test_question_references_attached_file_true_when_question_has_no_content_words() -> None:
    # A pronoun-style follow-up ("What about this one?") has nothing to
    # judge relevance from in isolation — default to relevant so
    # conversation-history resolution (Spec FV10.4) gets a chance instead
    # of this gate silently rerouting a legitimate follow-up.
    file = _regional_sales_file()

    assert question_references_attached_file("What about this one?", file)


def test_question_references_any_attached_file_true_when_any_file_is_unstructured() -> None:
    # An unstructured file's own relevance is FileScopedRetriever's job
    # (see 10-followups/06) — this gate must not preempt that.
    files = (_regional_sales_file(), _unstructured_file("ufile_notes"))

    assert question_references_any_attached_file(
        "Compare total ticket count by product in H1 2026.", files
    )


def test_question_references_any_attached_file_false_when_all_structured_and_irrelevant() -> None:
    files = (_regional_sales_file(),)

    assert not question_references_any_attached_file(
        "Compare total ticket count by product in H1 2026.", files
    )


def test_question_references_any_attached_file_false_for_empty_file_list() -> None:
    assert not question_references_any_attached_file("Any question at all.", ())
