import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from chatbi.files import (
    FileShareRecord,
    InMemoryFileRepository,
    UserUploadedFile,
    connect_psycopg,
    postgres_file_repository_from_psycopg,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file(**overrides: object) -> UserUploadedFile:
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


def test_save_and_get_roundtrip() -> None:
    repository = InMemoryFileRepository()
    file = _file()

    repository.save(file)

    assert repository.get("ufile_abc123") == file


def test_get_returns_none_for_unknown_file_id() -> None:
    repository = InMemoryFileRepository()

    assert repository.get("ufile_missing") is None


def test_soft_delete_sets_deleted_at_and_hides_from_list_by_owner() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file())
    deleted_at = _now()

    repository.soft_delete("ufile_abc123", deleted_at=deleted_at)

    stored = repository.get("ufile_abc123")
    assert stored is not None
    assert stored.deleted_at == deleted_at
    assert repository.list_by_owner("org_1", "user_1") == ()


def test_soft_delete_on_unknown_file_id_is_a_no_op() -> None:
    repository = InMemoryFileRepository()

    repository.soft_delete("ufile_missing", deleted_at=_now())  # must not raise


def test_list_by_owner_excludes_other_users_and_orgs() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_a", user_id="user_1"))
    repository.save(_file(file_id="ufile_b", user_id="user_2"))
    repository.save(_file(file_id="ufile_c", org_id="org_2", user_id="user_1"))

    results = repository.list_by_owner("org_1", "user_1")

    assert [file.file_id for file in results] == ["ufile_a"]


def test_list_by_owner_orders_newest_first() -> None:
    repository = InMemoryFileRepository()
    older = _now() - timedelta(days=1)
    newer = _now()
    repository.save(_file(file_id="ufile_old", created_at=older))
    repository.save(_file(file_id="ufile_new", file_group_id="fgrp_2", created_at=newer))

    results = repository.list_by_owner("org_1", "user_1")

    assert [file.file_id for file in results] == ["ufile_new", "ufile_old"]


def test_list_by_owner_filters_by_scope_and_status() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_ready", status="ready"))
    repository.save(
        _file(
            file_id="ufile_processing",
            file_group_id="fgrp_2",
            status="processing",
            schema_json=None,
            row_count=None,
        )
    )

    assert [f.file_id for f in repository.list_by_owner("org_1", "user_1", status="ready")] == [
        "ufile_ready"
    ]
    assert {
        f.file_id for f in repository.list_by_owner("org_1", "user_1", scope="user")
    } == {"ufile_ready", "ufile_processing"}


def test_list_by_owner_defaults_to_latest_versions_only() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_v1", version_number=1, is_latest=False))
    repository.save(_file(file_id="ufile_v2", version_number=2, is_latest=True))

    assert [f.file_id for f in repository.list_by_owner("org_1", "user_1")] == ["ufile_v2"]
    assert {f.file_id for f in repository.list_by_owner("org_1", "user_1", all_versions=True)} == {
        "ufile_v1",
        "ufile_v2",
    }


def test_list_versions_orders_by_version_number_descending() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_v1", version_number=1, is_latest=False))
    repository.save(_file(file_id="ufile_v2", version_number=2, is_latest=True))

    versions = repository.list_versions("fgrp_1")

    assert [f.file_id for f in versions] == ["ufile_v2", "ufile_v1"]


def test_list_active_returns_non_deleted_files_across_all_owners() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_a", user_id="user_1"))
    repository.save(_file(file_id="ufile_b", org_id="org_2", user_id="user_2"))
    repository.save(_file(file_id="ufile_deleted", user_id="user_1", deleted_at=_now()))

    active = repository.list_active()

    assert {f.file_id for f in active} == {"ufile_a", "ufile_b"}


def test_list_by_org_returns_files_from_every_uploader_in_the_org() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_a", user_id="analyst_1"))
    repository.save(_file(file_id="ufile_b", user_id="analyst_2"))
    repository.save(_file(file_id="ufile_c", org_id="org_2", user_id="analyst_1"))

    files = repository.list_by_org("org_1")

    assert {f.file_id for f in files} == {"ufile_a", "ufile_b"}


def test_list_by_org_filters_by_uploader_status_type_and_filename_search() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_a", user_id="alice@acme.com", original_name="q1.csv"))
    repository.save(_file(file_id="ufile_b", user_id="bob@acme.com", original_name="q2.csv", status="processing"))
    repository.save(
        _file(
            file_id="ufile_c",
            user_id="alice@acme.com",
            original_name="policy.pdf",
            file_type="unstructured",
            schema_json=None,
            row_count=None,
            chunk_count=1,
        )
    )

    assert {f.file_id for f in repository.list_by_org("org_1", user_id="alice")} == {"ufile_a", "ufile_c"}
    assert {f.file_id for f in repository.list_by_org("org_1", status="processing")} == {"ufile_b"}
    assert {f.file_id for f in repository.list_by_org("org_1", file_type="unstructured")} == {"ufile_c"}
    assert {f.file_id for f in repository.list_by_org("org_1", q="policy")} == {"ufile_c"}


def test_list_by_org_paginates_and_count_by_org_matches_full_filtered_total() -> None:
    repository = InMemoryFileRepository()
    for i in range(5):
        repository.save(
            _file(
                file_id=f"ufile_{i}",
                user_id="analyst_1",
                created_at=_now() + timedelta(seconds=i),
            )
        )

    first_page = repository.list_by_org("org_1", limit=2, offset=0)
    second_page = repository.list_by_org("org_1", limit=2, offset=2)

    assert len(first_page) == 2
    assert len(second_page) == 2
    assert repository.count_by_org("org_1") == 5
    # Newest first, so the first page should be the two most recently created.
    assert first_page[0].file_id == "ufile_4"
    assert first_page[1].file_id == "ufile_3"


def test_save_share_and_share_by_id_roundtrip() -> None:
    repository = InMemoryFileRepository()
    share = FileShareRecord(
        share_id="shr_1",
        file_id="ufile_abc123",
        granted_by="user_1",
        granted_to="user_2",
        created_at=_now(),
    )

    repository.save_share(share)

    assert repository.share_by_id("shr_1") == share


def test_revoke_share_sets_revoked_at() -> None:
    repository = InMemoryFileRepository()
    repository.save_share(
        FileShareRecord(
            share_id="shr_1",
            file_id="ufile_abc123",
            granted_by="user_1",
            granted_to="user_2",
            created_at=_now(),
        )
    )
    revoked_at = _now()

    repository.revoke_share("shr_1", revoked_at=revoked_at)

    share = repository.share_by_id("shr_1")
    assert share is not None
    assert share.revoked_at == revoked_at


def test_revoke_share_is_idempotent() -> None:
    repository = InMemoryFileRepository()
    repository.save_share(
        FileShareRecord(
            share_id="shr_1",
            file_id="ufile_abc123",
            granted_by="user_1",
            granted_to="user_2",
            created_at=_now(),
        )
    )
    first_revoked_at = _now()
    repository.revoke_share("shr_1", revoked_at=first_revoked_at)

    repository.revoke_share("shr_1", revoked_at=_now() + timedelta(minutes=5))

    share = repository.share_by_id("shr_1")
    assert share is not None
    assert share.revoked_at == first_revoked_at


def test_revoke_share_on_unknown_share_id_is_a_no_op() -> None:
    repository = InMemoryFileRepository()

    repository.revoke_share("shr_missing", revoked_at=_now())  # must not raise


def test_hard_delete_removes_the_metadata_row() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file())

    repository.hard_delete("ufile_abc123")

    assert repository.get("ufile_abc123") is None


def test_hard_delete_on_unknown_file_id_is_a_no_op() -> None:
    repository = InMemoryFileRepository()

    repository.hard_delete("ufile_missing")  # must not raise


def test_list_by_owner_excludes_archived_files() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_active"))
    repository.save(_file(file_id="ufile_archived", file_group_id="fgrp_2", archived_at=_now()))

    results = repository.list_by_owner("org_1", "user_1")

    assert [f.file_id for f in results] == ["ufile_active"]


def test_list_by_org_excludes_archived_files() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(file_id="ufile_active"))
    repository.save(_file(file_id="ufile_archived", file_group_id="fgrp_2", archived_at=_now()))

    files = repository.list_by_org("org_1")

    assert {f.file_id for f in files} == {"ufile_active"}
    assert repository.count_by_org("org_1") == 1


def test_find_archived_by_content_hash_matches_same_user_only() -> None:
    repository = InMemoryFileRepository()
    repository.save(
        _file(
            file_id="ufile_archived",
            content_hash="hash_dup",
            archived_at=_now(),
        )
    )
    repository.save(
        _file(
            file_id="ufile_other_user_archived",
            file_group_id="fgrp_2",
            user_id="user_2",
            content_hash="hash_dup",
            archived_at=_now(),
        )
    )

    match = repository.find_archived_by_content_hash("user_1", "hash_dup")

    assert match is not None
    assert match.file_id == "ufile_archived"
    assert repository.find_archived_by_content_hash("user_2", "hash_no_match") is None


def test_find_archived_by_content_hash_ignores_non_archived_files() -> None:
    repository = InMemoryFileRepository()
    repository.save(_file(content_hash="hash_dup"))

    assert repository.find_archived_by_content_hash("user_1", "hash_dup") is None


def test_list_archived_by_org_returns_only_archived_files_newest_first() -> None:
    repository = InMemoryFileRepository()
    earlier = _now() - timedelta(days=1)
    later = _now()
    repository.save(_file(file_id="ufile_active"))
    repository.save(_file(file_id="ufile_archived_old", file_group_id="fgrp_2", archived_at=earlier))
    repository.save(_file(file_id="ufile_archived_new", file_group_id="fgrp_3", archived_at=later))
    repository.save(_file(file_id="ufile_other_org", file_group_id="fgrp_4", org_id="org_2", archived_at=later))

    archived = repository.list_archived_by_org("org_1")

    assert [f.file_id for f in archived] == ["ufile_archived_new", "ufile_archived_old"]


def test_shares_for_file_returns_only_matching_file_ordered_by_created_at() -> None:
    repository = InMemoryFileRepository()
    earlier = _now() - timedelta(minutes=5)
    later = _now()
    repository.save_share(
        FileShareRecord(
            share_id="shr_1",
            file_id="ufile_abc123",
            granted_by="user_1",
            granted_to="user_2",
            created_at=later,
        )
    )
    repository.save_share(
        FileShareRecord(
            share_id="shr_2",
            file_id="ufile_abc123",
            granted_by="user_1",
            granted_to="user_3",
            created_at=earlier,
        )
    )
    repository.save_share(
        FileShareRecord(
            share_id="shr_3",
            file_id="ufile_other",
            granted_by="user_1",
            granted_to="user_2",
            created_at=earlier,
        )
    )

    shares = repository.shares_for_file("ufile_abc123")

    assert [share.share_id for share in shares] == ["shr_2", "shr_1"]


def test_postgres_file_repository_live_insert_update_select() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for live PostgreSQL file repository integration.")

    connection = connect_psycopg(database_url)
    repository = postgres_file_repository_from_psycopg(connection)
    repository.initialize_schema()

    file_id = f"ufile_live_{uuid4().hex[:16]}"
    file_group_id = f"fgrp_live_{uuid4().hex[:16]}"
    file = _file(file_id=file_id, file_group_id=file_group_id)

    repository.save(file)
    fetched = repository.get(file_id)

    repository.soft_delete(file_id, deleted_at=_now())
    after_delete = repository.get(file_id)

    connection.close()

    assert fetched == file
    assert after_delete is not None


def test_postgres_file_repository_list_by_org_and_count_by_org_live() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for live PostgreSQL file repository integration.")

    connection = connect_psycopg(database_url)
    repository = postgres_file_repository_from_psycopg(connection)
    repository.initialize_schema()

    org_id = f"org_live_{uuid4().hex[:12]}"
    group_id = f"fgrp_live_{uuid4().hex[:12]}"
    repository.save(
        _file(
            file_id=f"ufile_live_{uuid4().hex[:12]}",
            org_id=org_id,
            user_id="alice@acme.com",
            original_name="q1_review.pdf",
            file_type="unstructured",
            file_group_id=group_id,
            schema_json=None,
            row_count=None,
            chunk_count=1,
        )
    )
    other_group_id = f"fgrp_live_{uuid4().hex[:12]}"
    repository.save(
        _file(
            file_id=f"ufile_live_{uuid4().hex[:12]}",
            org_id=org_id,
            user_id="bob@acme.com",
            original_name="q2_revenue.csv",
            file_group_id=other_group_id,
        )
    )

    all_files = repository.list_by_org(org_id)
    alice_only = repository.list_by_org(org_id, user_id="alice")
    pdf_only = repository.list_by_org(org_id, file_type="unstructured")
    by_name = repository.list_by_org(org_id, q="revenue")
    total = repository.count_by_org(org_id)

    connection.close()

    assert len(all_files) == 2
    assert {f.user_id for f in alice_only} == {"alice@acme.com"}
    assert {f.original_name for f in pdf_only} == {"q1_review.pdf"}
    assert {f.original_name for f in by_name} == {"q2_revenue.csv"}
    assert total == 2
