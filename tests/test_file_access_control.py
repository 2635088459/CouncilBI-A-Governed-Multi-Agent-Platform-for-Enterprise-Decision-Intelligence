from datetime import datetime, timezone

from chatbi.files import (
    FileAccessChecker,
    FileAccessDecision,
    FileShareRecord,
    FileVersionManager,
    UserUploadedFile,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_target",
        org_id="org_1",
        user_id="user_b",
        original_name="revenue.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=1024,
        storage_key="org_1/user_b/ufile_target/revenue.csv",
        content_hash="hash_target",
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


def test_owner_is_always_allowed() -> None:
    file = _file(user_id="user_a")

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="business_user",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.ALLOW


def test_non_owner_with_no_shares_is_denied() -> None:
    file = _file(user_id="user_b", scope="user")

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="business_user",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.DENY


def test_analyst_can_read_org_scoped_file_in_same_org() -> None:
    file = _file(scope="org", org_id="org_1")

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="analyst",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.ALLOW


def test_analyst_cannot_read_org_scoped_file_in_a_different_org() -> None:
    file = _file(scope="org", org_id="org_2")

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="analyst",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.DENY


def test_business_user_cannot_read_org_scoped_file() -> None:
    file = _file(scope="org", org_id="org_1")

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="business_user",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.DENY


def test_team_scoped_file_allowed_with_active_share() -> None:
    file = _file(scope="team")
    active_share = FileShareRecord(
        share_id="shr_1",
        file_id="ufile_target",
        granted_by="user_b",
        granted_to="user_a",
        created_at=_now(),
    )

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="business_user",
        file=file,
        shares=(active_share,),
    )

    assert decision == FileAccessDecision.ALLOW


def test_team_scoped_file_denied_with_revoked_share() -> None:
    file = _file(scope="team")
    revoked_share = FileShareRecord(
        share_id="shr_1",
        file_id="ufile_target",
        granted_by="user_b",
        granted_to="user_a",
        created_at=_now(),
        revoked_at=_now(),
    )

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="business_user",
        file=file,
        shares=(revoked_share,),
    )

    assert decision == FileAccessDecision.DENY


def test_team_scoped_file_denied_when_share_is_for_a_different_file() -> None:
    file = _file(scope="team")
    unrelated_share = FileShareRecord(
        share_id="shr_1",
        file_id="ufile_other",
        granted_by="user_b",
        granted_to="user_a",
        created_at=_now(),
    )

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="business_user",
        file=file,
        shares=(unrelated_share,),
    )

    assert decision == FileAccessDecision.DENY


def test_admin_can_read_any_file_in_their_org_regardless_of_scope() -> None:
    file = _file(scope="session", session_id="ses_1")

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="admin",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.ALLOW


def test_admin_cannot_read_a_file_in_a_different_org() -> None:
    file = _file(scope="session", session_id="ses_1", org_id="org_2")

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="admin",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.DENY


def test_archived_file_denies_its_own_owner() -> None:
    # TC-FV10-129: file.user_id == requester_user_id must NOT short-circuit
    # the archived precondition.
    file = _file(user_id="user_a", archived_at=_now())

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="business_user",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.DENY


def test_archived_file_denies_a_user_with_an_active_share() -> None:
    # TC-FV10-130
    file = _file(scope="team", archived_at=_now())
    active_share = FileShareRecord(
        share_id="shr_1",
        file_id="ufile_target",
        granted_by="user_b",
        granted_to="user_a",
        created_at=_now(),
    )

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="business_user",
        file=file,
        shares=(active_share,),
    )

    assert decision == FileAccessDecision.DENY


def test_archived_file_allows_admin_in_the_same_org() -> None:
    # TC-FV10-131
    file = _file(archived_at=_now())

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="admin",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.ALLOW


def test_archived_file_denies_admin_in_a_different_org() -> None:
    file = _file(archived_at=_now(), org_id="org_2")

    decision = FileAccessChecker().check(
        requester_user_id="user_a",
        requester_org_id="org_1",
        role="admin",
        file=file,
        shares=(),
    )

    assert decision == FileAccessDecision.DENY


def test_on_upload_with_existing_group_supersedes_the_old_version() -> None:
    old_record = _file(file_id="ufile_v1", file_group_id="fgrp_1", version_number=1, is_latest=True)

    assignment = FileVersionManager().on_upload("fgrp_1", old_record)

    assert assignment.version_number == 2
    assert assignment.file_group_id == "fgrp_1"
    assert assignment.superseded_previous_latest is not None
    assert assignment.superseded_previous_latest.is_latest is False
    assert assignment.superseded_previous_latest.file_id == "ufile_v1"


def test_on_upload_without_existing_group_starts_a_new_chain() -> None:
    assignment = FileVersionManager().on_upload(None)

    assert assignment.version_number == 1
    assert assignment.file_group_id.startswith("fgrp_")
    assert assignment.superseded_previous_latest is None


def test_on_upload_never_reuses_the_previous_version_file_id() -> None:
    old_record = _file(file_id="ufile_v1", file_group_id="fgrp_1", version_number=1, is_latest=True)

    assignment = FileVersionManager().on_upload("fgrp_1", old_record)

    assert assignment.file_id != old_record.file_id
    assert assignment.file_id.startswith("ufile_")
