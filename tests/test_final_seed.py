import pytest
from pathlib import Path

from chatbi.final_seed import (
    SEED_PROFILES,
    SeedDataset,
    SeedProfile,
    SeedProfileName,
    build_seed_dataset,
    main,
    read_seed_artifact,
    seed_dataset_to_artifact,
    validate_seed_artifact,
    validate_seed_dataset,
)


def test_seed_profiles_include_small_medium_and_large() -> None:
    assert set(SEED_PROFILES) == {
        SeedProfileName.SMALL,
        SeedProfileName.MEDIUM,
        SeedProfileName.LARGE,
    }
    assert SEED_PROFILES[SeedProfileName.SMALL].org_count == 2
    assert SEED_PROFILES[SeedProfileName.MEDIUM].business_row_count == 100_000
    assert SEED_PROFILES[SeedProfileName.LARGE].explicit_only is True


def test_small_seed_is_repeatable_and_idempotent_with_reset_mode() -> None:
    first = build_seed_dataset(SeedProfileName.SMALL, reset=True)
    second = build_seed_dataset(SeedProfileName.SMALL, reset=True)

    assert first.organizations == second.organizations
    assert first.users == second.users
    assert first.orders == second.orders
    assert first.documents == second.documents
    assert first.vector_chunk_count == second.vector_chunk_count


def test_small_seed_quality_validates_required_tables_tenants_foreign_keys_and_metrics() -> None:
    dataset = build_seed_dataset(SeedProfileName.SMALL)

    report = validate_seed_dataset(dataset)

    assert report.passed
    assert len(dataset.organizations) == 2
    assert len(dataset.users) == 5
    assert len(dataset.orders) == 240
    assert dataset.vector_chunk_count > 0


def test_quality_validates_chunk_count_equals_vector_count() -> None:
    dataset = build_seed_dataset(SeedProfileName.SMALL)
    corrupted = SeedDataset(
        profile=dataset.profile,
        organizations=dataset.organizations,
        users=dataset.users,
        customers=dataset.customers,
        orders=dataset.orders,
        refunds=dataset.refunds,
        documents=dataset.documents,
        vector_chunk_count=dataset.vector_chunk_count,
        vector_count=dataset.vector_count + 1,
        vector_rag_service=dataset.vector_rag_service,
    )

    report = validate_seed_dataset(corrupted)

    assert not report.passed
    assert "VECTOR_COUNT_MISMATCH" in {violation.code for violation in report.violations}


def test_seeded_business_question_retrieves_matching_document_evidence() -> None:
    dataset = build_seed_dataset(SeedProfileName.MEDIUM)
    first_org = str(dataset.organizations[0]["org_id"])

    answer = dataset.vector_rag_service.answer(
        trace_id="trc_seeded_question",
        org_id=first_org,
        question="Why did revenue change after campaign spend paused?",
        permission_tags=("analyst",),
    )

    assert answer.missing_evidence_warning is None
    assert answer.evidence_chunks
    assert all(chunk.org_id == first_org for chunk in answer.evidence_chunks)
    assert "campaign spend paused" in answer.answer


def test_tenant_leakage_quality_check_fails_on_mixed_customer_order_record() -> None:
    dataset = build_seed_dataset(SeedProfileName.SMALL)
    first_order = dict(dataset.orders[0])
    other_org_customer = next(
        customer
        for customer in dataset.customers
        if customer["org_id"] != first_order["org_id"]
    )
    mixed_order = {
        **first_order,
        "order_id": 999_999,
        "customer_id": other_org_customer["customer_id"],
    }
    corrupted = SeedDataset(
        profile=dataset.profile,
        organizations=dataset.organizations,
        users=dataset.users,
        customers=dataset.customers,
        orders=(mixed_order,),
        refunds=dataset.refunds,
        documents=dataset.documents,
        vector_chunk_count=dataset.vector_chunk_count,
        vector_count=dataset.vector_count,
        vector_rag_service=dataset.vector_rag_service,
    )

    report = validate_seed_dataset(corrupted)

    assert not report.passed
    assert "TENANT_LEAKAGE" in {violation.code for violation in report.violations}


def test_large_seed_requires_explicit_allow_large_flag() -> None:
    with pytest.raises(ValueError, match="large seed must be explicitly enabled"):
        build_seed_dataset(SeedProfileName.LARGE)


def test_large_seed_can_be_generated_explicitly_for_load_prep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        SEED_PROFILES,
        SeedProfileName.LARGE,
        SeedProfile(
            name=SeedProfileName.LARGE,
            org_count=3,
            user_count=9,
            business_row_count=30,
            document_count=3,
            chunk_token_limit=32,
            explicit_only=True,
        ),
    )

    dataset = build_seed_dataset(SeedProfileName.LARGE, allow_large=True)

    assert dataset.profile.name is SeedProfileName.LARGE
    assert len(dataset.organizations) == 3
    assert len(dataset.orders) == 30


def test_final_seed_cli_runs_small_profile(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(("--profile", "small"))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "seed_profile=small" in output
    assert "quality=passed" in output


def test_final_seed_cli_requires_allow_large(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(ValueError, match="large seed must be explicitly enabled"):
        main(("--profile", "large"))


def test_seed_dataset_artifact_contains_counts_tables_and_documents() -> None:
    dataset = build_seed_dataset(SeedProfileName.SMALL)

    artifact = seed_dataset_to_artifact(dataset)

    assert artifact["profile"] == "small"
    counts = artifact["counts"]
    assert isinstance(counts, dict)
    assert counts["organizations"] == 2
    assert counts["orders"] == 240
    assert counts["vector_chunks"] == dataset.vector_chunk_count
    tables = artifact["tables"]
    assert isinstance(tables, dict)
    assert len(tables["orders"]) == 240
    documents = artifact["documents"]
    assert isinstance(documents, list)
    assert documents[0]["document_id"].startswith("doc_seed_")


def test_final_seed_cli_writes_deterministic_json_artifact(tmp_path: Path) -> None:
    output_a = Path(tmp_path) / "seed-a.json"
    output_b = Path(tmp_path) / "seed-b.json"

    first_exit = main(("--profile", "small", "--output-json", str(output_a)))
    second_exit = main(("--profile", "small", "--output-json", str(output_b)))

    assert first_exit == 0
    assert second_exit == 0
    assert output_a.read_text(encoding="utf-8") == output_b.read_text(encoding="utf-8")
    assert '"profile": "small"' in output_a.read_text(encoding="utf-8")


def test_seed_artifact_can_be_read_and_quality_checked(tmp_path: Path) -> None:
    output_path = Path(tmp_path) / "seed.json"
    assert main(("--profile", "small", "--output-json", str(output_path))) == 0

    artifact = read_seed_artifact(output_path)
    report = validate_seed_artifact(artifact)

    assert report.passed
    assert report.profile_name is SeedProfileName.SMALL


def test_seed_artifact_quality_fails_on_vector_count_mismatch() -> None:
    artifact = seed_dataset_to_artifact(build_seed_dataset(SeedProfileName.SMALL))
    counts = artifact["counts"]
    assert isinstance(counts, dict)
    artifact["counts"] = {
        **counts,
        "vectors": int(counts["vector_chunks"]) + 1,
    }

    report = validate_seed_artifact(artifact)

    assert not report.passed
    assert "VECTOR_COUNT_MISMATCH" in {violation.code for violation in report.violations}


def test_seed_artifact_quality_fails_on_tenant_leakage() -> None:
    artifact = seed_dataset_to_artifact(build_seed_dataset(SeedProfileName.SMALL))
    tables = artifact["tables"]
    assert isinstance(tables, dict)
    orders = list(tables["orders"])
    customers = list(tables["customers"])
    first_order = dict(orders[0])
    other_org_customer = next(
        customer
        for customer in customers
        if customer["org_id"] != first_order["org_id"]
    )
    orders[0] = {
        **first_order,
        "customer_id": other_org_customer["customer_id"],
    }
    tables["orders"] = orders

    report = validate_seed_artifact(artifact)

    assert not report.passed
    assert "TENANT_LEAKAGE" in {violation.code for violation in report.violations}


def test_final_seed_cli_validates_existing_json_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = Path(tmp_path) / "seed.json"
    assert main(("--profile", "small", "--output-json", str(output_path))) == 0

    exit_code = main(("--validate-json", str(output_path)))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "seed_artifact=" in output
    assert "quality=passed" in output
