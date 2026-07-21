import pytest

from chatbi.evaluation_cases import load_eval_cases


def test_load_eval_cases_from_json_style_mappings() -> None:
    cases = load_eval_cases(
        (
            {
                "case_id": " case_revenue ",
                "question": " Show revenue trend. ",
                "expected_metric_id": " revenue ",
                "expected_sql_fragments": [" select ", "revenue", " orders "],
                "permission_context": {"role": "analyst"},
            },
            {
                "case_id": "case_dangerous_sql",
                "question": "DROP TABLE orders",
                "expected_metric_id": None,
                "expected_sql_fragments": ["drop table", "orders"],
                "permission_context": {"role": "analyst"},
            },
        )
    )

    assert [case.case_id for case in cases] == ["case_revenue", "case_dangerous_sql"]
    assert cases[0].question == "Show revenue trend."
    assert cases[0].expected_metric_id == "revenue"
    assert cases[0].expected_sql_fragments == ("select", "revenue", "orders")
    assert cases[0].permission_context["role"] == "analyst"
    assert cases[1].expected_metric_id is None


def test_load_eval_cases_defaults_optional_fields() -> None:
    cases = load_eval_cases(
        (
            {
                "case_id": "case_minimal",
                "question": "Show revenue.",
            },
        )
    )

    assert cases[0].expected_metric_id is None
    assert cases[0].expected_sql_fragments == ()
    assert cases[0].expected_chunk_ids == ()
    assert cases[0].permission_context == {}


def test_load_eval_cases_populates_expected_chunk_ids() -> None:
    # TC-FV03-039 / AC-FV03-021.
    cases = load_eval_cases(
        (
            {
                "case_id": "case_retrieval",
                "question": "Why did revenue drop?",
                "expected_chunk_ids": [" doc_campaign_chunk_1 ", "doc_campaign_chunk_2"],
            },
        )
    )

    assert cases[0].expected_chunk_ids == ("doc_campaign_chunk_1", "doc_campaign_chunk_2")


def test_load_eval_cases_defaults_expected_chunk_ids_to_empty_tuple() -> None:
    # TC-FV03-040 / AC-FV03-021.
    cases = load_eval_cases(
        (
            {
                "case_id": "case_no_retrieval",
                "question": "Show revenue trend.",
            },
        )
    )

    assert cases[0].expected_chunk_ids == ()


def test_load_eval_cases_rejects_duplicate_case_ids() -> None:
    with pytest.raises(ValueError, match="Duplicate eval case_id case_one"):
        load_eval_cases(
            (
                {"case_id": "case_one", "question": "Show revenue."},
                {"case_id": "case_one", "question": "Show orders."},
            )
        )


def test_load_eval_cases_rejects_invalid_required_fields() -> None:
    with pytest.raises(ValueError, match="requires non-empty question"):
        load_eval_cases(({"case_id": "case_missing_question", "question": " "},))


def test_load_eval_cases_rejects_invalid_list_and_permission_context() -> None:
    with pytest.raises(ValueError, match="expected_sql_fragments must be a list"):
        load_eval_cases(
            (
                {
                    "case_id": "case_bad_fragments",
                    "question": "Show revenue.",
                    "expected_sql_fragments": "select",
                },
            )
        )

    with pytest.raises(ValueError, match="permission_context must be an object"):
        load_eval_cases(
            (
                {
                    "case_id": "case_bad_permissions",
                    "question": "Show revenue.",
                    "permission_context": ["analyst"],
                },
            )
        )
