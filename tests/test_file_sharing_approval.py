"""Spec FV10.2: File Sharing Approval Workflow.

Unit tests exercise ``FileShareApprovalService`` directly against
``InMemoryFileRepository``/``InMemoryAuthStore``; integration tests drive the
real HTTP endpoints end to end, including the Spec FV10.1 RAG-visibility
side effect of approval.
"""

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.auth import (
    AuthService,
    InMemoryAuthStore,
    PasswordHasher,
    TokenService,
    permissions_for_roles,
)
from chatbi.files import (
    FileShareApprovalService,
    FileShareRecord,
    InMemoryFileRepository,
    InMemoryFileVectorSink,
    InMemoryObjectStorageAdapter,
    NotFileOwnerError,
    PendingShareRequestExistsError,
    PostgresFileRepository,
    ShareRequestNotFoundError,
    ShareRequestNotPendingError,
    TextChunk,
    UserUploadedFile,
    file_share_visibility_resolver,
)
from chatbi.knowledge import InMemoryKnowledgeStore, KnowledgeDocument, RetrievalQuery


_PASSWORD = "correct horse battery staple"


# --- shared fixtures --------------------------------------------------------


def _seed_org_user(auth_store: InMemoryAuthStore, org_id: str, email: str, role: str) -> str:
    user = auth_store.create_user(
        email=email,
        password_hash="hash",
        display_name=email,
        org_id=org_id,
        roles=(role,),
        permissions=permissions_for_roles((role,)),
    )
    return user.user_id


def _seed_file(
    repository: InMemoryFileRepository,
    *,
    file_id: str,
    org_id: str,
    user_id: str,
    scope: str = "team",
    file_type: str = "structured",
    promoted_to_doc_id: str | None = None,
) -> UserUploadedFile:
    fields: dict[str, Any] = dict(
        file_id=file_id,
        org_id=org_id,
        user_id=user_id,
        original_name="runbook.pdf" if file_type == "unstructured" else "forecast.csv",
        file_type=file_type,
        mime_type="application/pdf" if file_type == "unstructured" else "text/csv",
        size_bytes=1024,
        storage_key=f"{org_id}/{user_id}/{file_id}/file",
        content_hash=f"hash_{file_id}",
        status="ready",
        scope=scope,
        file_group_id=f"fgrp_{file_id}",
        version_number=1,
        is_latest=True,
        created_at=datetime.now(timezone.utc),
        promoted_to_doc_id=promoted_to_doc_id,
    )
    if file_type == "structured":
        fields["schema_json"] = {"columns": []}
        fields["row_count"] = 0
    else:
        fields["chunk_count"] = 1
    file_record = UserUploadedFile(**fields)  # type: ignore[arg-type]
    repository.save(file_record)
    return file_record


# --- unit tests: request lifecycle (TC-FV10-116..118) -----------------------


def test_submit_request_succeeds_when_no_pending_request_exists() -> None:
    # TC-FV10-116
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    _seed_file(repository, file_id="ufile_share_a0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)

    request = service.submit_request(
        "ufile_share_a0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    assert request.status == "pending"
    assert request.request_id.startswith("req_share_")
    assert repository.pending_share_request_for_file("ufile_share_a0000000000000000001") == request


def test_submit_request_conflicts_when_a_pending_request_already_exists() -> None:
    # TC-FV10-117
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    _seed_file(repository, file_id="ufile_share_b0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    service.submit_request(
        "ufile_share_b0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    with pytest.raises(PendingShareRequestExistsError):
        service.submit_request(
            "ufile_share_b0000000000000000001",
            requester_user_id=owner_id,
            requester_org_id="org_acme",
            requester_role="analyst",
        )


def test_submit_request_allowed_again_once_prior_request_is_decided() -> None:
    # TC-FV10-118
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    admin_id = _seed_org_user(auth_store, "org_acme", "admin@example.com", "admin")
    _seed_file(repository, file_id="ufile_share_c0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    first = service.submit_request(
        "ufile_share_c0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )
    service.reject(first.request_id, admin_user_id=admin_id, admin_org_id="org_acme")

    second = service.submit_request(
        "ufile_share_c0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    assert second.status == "pending"
    assert second.request_id != first.request_id


def test_submit_request_by_a_non_owner_raises() -> None:
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    other_id = _seed_org_user(auth_store, "org_acme", "other@example.com", "analyst")
    _seed_file(repository, file_id="ufile_share_k0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)

    with pytest.raises(NotFileOwnerError):
        service.submit_request(
            "ufile_share_k0000000000000000001",
            requester_user_id=other_id,
            requester_org_id="org_acme",
            requester_role="analyst",
        )


# --- unit tests: approval fan-out (TC-FV10-119..123) -------------------------


def test_approve_fans_out_to_every_other_analyst_in_org_and_no_other_role() -> None:
    # TC-FV10-119 / NFR-FV10-013
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    colleague_id = _seed_org_user(auth_store, "org_acme", "colleague@example.com", "analyst")
    other_analyst_id = _seed_org_user(auth_store, "org_acme", "other_analyst@example.com", "analyst")
    admin_id = _seed_org_user(auth_store, "org_acme", "admin@example.com", "admin")
    biz_id = _seed_org_user(auth_store, "org_acme", "biz@example.com", "business_user")
    _seed_file(repository, file_id="ufile_share_d0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    request = service.submit_request(
        "ufile_share_d0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    approved = service.approve(request.request_id, admin_user_id=admin_id, admin_org_id="org_acme")

    granted_to_ids = {share.granted_to for share in repository.shares_for_file("ufile_share_d0000000000000000001")}
    assert granted_to_ids == {colleague_id, other_analyst_id}
    assert admin_id not in granted_to_ids
    assert biz_id not in granted_to_ids
    assert owner_id not in granted_to_ids
    assert approved.status == "approved"
    assert approved.decided_by == admin_id
    assert approved.decided_at is not None


def test_approve_does_not_fan_out_to_a_different_org_even_with_a_matching_role() -> None:
    # TC-FV10-120
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    colleague_id = _seed_org_user(auth_store, "org_acme", "colleague@example.com", "analyst")
    outsider_id = _seed_org_user(auth_store, "org_other", "outsider@example.com", "analyst")
    admin_id = _seed_org_user(auth_store, "org_acme", "admin@example.com", "admin")
    _seed_file(repository, file_id="ufile_share_e0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    request = service.submit_request(
        "ufile_share_e0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    service.approve(request.request_id, admin_user_id=admin_id, admin_org_id="org_acme")

    granted_to_ids = {share.granted_to for share in repository.shares_for_file("ufile_share_e0000000000000000001")}
    assert granted_to_ids == {colleague_id}
    assert outsider_id not in granted_to_ids


class _FailingAfterNCallsConnection:
    """Fake ``FilePostgresConnection`` that raises partway through a batch.

    Used to prove NFR-FV10-013's "either every matching user receives a
    FileShareRecord, or none do" without needing a live database: the first
    INSERT succeeds, the second raises, and the test asserts commit() was
    never reached and rollback() was called.
    """

    def __init__(self, fail_on_call: int) -> None:
        self._fail_on_call = fail_on_call
        self._execute_calls = 0
        self.committed = False
        self.rolled_back = False

    def execute(self, sql: str, params: object = ()) -> None:
        self._execute_calls += 1
        if self._execute_calls == self._fail_on_call:
            raise RuntimeError("simulated write failure")

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> tuple[object, ...]:
        return ()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def test_save_shares_rolls_back_and_commits_nothing_when_a_later_insert_fails() -> None:
    # NFR-FV10-013, at the storage layer save_shares() relies on.
    connection = _FailingAfterNCallsConnection(fail_on_call=2)
    repository = PostgresFileRepository(connection)  # type: ignore[arg-type]
    now = datetime.now(timezone.utc)
    shares = (
        FileShareRecord(
            share_id="shr_batch_1",
            file_id="ufile_batch0000000000000000001",
            granted_by="owner_1",
            granted_to="user_1",
            created_at=now,
        ),
        FileShareRecord(
            share_id="shr_batch_2",
            file_id="ufile_batch0000000000000000001",
            granted_by="owner_1",
            granted_to="user_2",
            created_at=now,
        ),
    )

    with pytest.raises(RuntimeError):
        repository.save_shares(shares)

    assert connection.committed is False
    assert connection.rolled_back is True


def test_approve_for_structured_file_creates_shares_with_nothing_to_widen_in_rag() -> None:
    # TC-FV10-121: no promoted document exists for a structured (or never
    # promoted) file, so the shared-visibility resolver — the only
    # mechanism that could widen RAG visibility — has nothing to resolve.
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    colleague_id = _seed_org_user(auth_store, "org_acme", "colleague@example.com", "analyst")
    admin_id = _seed_org_user(auth_store, "org_acme", "admin@example.com", "admin")
    _seed_file(
        repository,
        file_id="ufile_share_f0000000000000000001",
        org_id="org_acme",
        user_id=owner_id,
        file_type="structured",
    )
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    request = service.submit_request(
        "ufile_share_f0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    approved = service.approve(request.request_id, admin_user_id=admin_id, admin_org_id="org_acme")

    assert approved.status == "approved"
    assert {share.granted_to for share in repository.shares_for_file("ufile_share_f0000000000000000001")} == {
        colleague_id
    }
    resolver = file_share_visibility_resolver(repository)
    unrelated_document = KnowledgeDocument(
        source_id="doc_unrelated",
        title="Unrelated",
        doc_type="policy",
        publish_time=datetime.now(timezone.utc),
        owner_user_id=owner_id,
    )
    assert resolver(unrelated_document) == frozenset()


def test_approve_for_promoted_unstructured_file_widens_rag_visibility_to_fanout_set() -> None:
    # TC-FV10-122 / AC-FV10-036
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    colleague_id = _seed_org_user(auth_store, "org_acme", "colleague@example.com", "analyst")
    unrelated_biz_id = _seed_org_user(auth_store, "org_acme", "biz@example.com", "business_user")
    admin_id = _seed_org_user(auth_store, "org_acme", "admin@example.com", "admin")
    _seed_file(
        repository,
        file_id="ufile_share_g0000000000000000001",
        org_id="org_acme",
        user_id=owner_id,
        file_type="unstructured",
        promoted_to_doc_id="doc_share_g",
    )
    knowledge_store = InMemoryKnowledgeStore(
        shared_visibility_resolver=file_share_visibility_resolver(repository)
    )
    knowledge_store.ingest_document(
        KnowledgeDocument(
            source_id="doc_share_g",
            title="Escalation runbook",
            doc_type="user_promoted",
            publish_time=datetime.now(timezone.utc),
            owner_user_id=owner_id,
        ),
        "Escalate P1 incidents to the on-call engineer within 15 minutes.",
    )
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    request = service.submit_request(
        "ufile_share_g0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    before_approval = knowledge_store.retrieve(
        RetrievalQuery(question="Escalate P1 incidents", requesting_user_id=colleague_id)
    )
    service.approve(request.request_id, admin_user_id=admin_id, admin_org_id="org_acme")
    after_colleague = knowledge_store.retrieve(
        RetrievalQuery(question="Escalate P1 incidents", requesting_user_id=colleague_id)
    )
    after_unrelated = knowledge_store.retrieve(
        RetrievalQuery(question="Escalate P1 incidents", requesting_user_id=unrelated_biz_id)
    )

    assert before_approval.evidence_list == ()
    assert tuple(item.source_id for item in after_colleague.evidence_list) == ("doc_share_g",)
    assert after_unrelated.evidence_list == ()


def test_reject_creates_no_shares_and_records_the_decision() -> None:
    # TC-FV10-123
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    _seed_org_user(auth_store, "org_acme", "colleague@example.com", "analyst")
    admin_id = _seed_org_user(auth_store, "org_acme", "admin@example.com", "admin")
    _seed_file(repository, file_id="ufile_share_h0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    request = service.submit_request(
        "ufile_share_h0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    rejected = service.reject(
        request.request_id, admin_user_id=admin_id, admin_org_id="org_acme", reason="Contains PII"
    )

    assert rejected.status == "rejected"
    assert rejected.decided_by == admin_id
    assert rejected.decided_at is not None
    assert rejected.reason == "Contains PII"
    assert repository.shares_for_file("ufile_share_h0000000000000000001") == ()


def test_approve_unknown_request_raises_not_found() -> None:
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)

    with pytest.raises(ShareRequestNotFoundError):
        service.approve("req_share_missing00000", admin_user_id="admin_1", admin_org_id="org_acme")


def test_approve_a_request_from_a_different_org_raises_not_found() -> None:
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    _seed_file(repository, file_id="ufile_share_i0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    request = service.submit_request(
        "ufile_share_i0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )

    with pytest.raises(ShareRequestNotFoundError):
        service.approve(request.request_id, admin_user_id="admin_x", admin_org_id="org_other")


def test_approve_an_already_decided_request_raises_not_pending() -> None:
    repository = InMemoryFileRepository()
    auth_store = InMemoryAuthStore()
    owner_id = _seed_org_user(auth_store, "org_acme", "owner@example.com", "analyst")
    admin_id = _seed_org_user(auth_store, "org_acme", "admin@example.com", "admin")
    _seed_file(repository, file_id="ufile_share_j0000000000000000001", org_id="org_acme", user_id=owner_id)
    service = FileShareApprovalService(repository=repository, auth_store=auth_store)
    request = service.submit_request(
        "ufile_share_j0000000000000000001",
        requester_user_id=owner_id,
        requester_org_id="org_acme",
        requester_role="analyst",
    )
    service.approve(request.request_id, admin_user_id=admin_id, admin_org_id="org_acme")

    with pytest.raises(ShareRequestNotPendingError):
        service.approve(request.request_id, admin_user_id=admin_id, admin_org_id="org_acme")


# --- HTTP integration tests --------------------------------------------------


def _fresh_auth_service() -> AuthService:
    return AuthService(token_service=TokenService(secret="test-secret"))


def _seed_user(auth_service: AuthService, org_id: str, email: str, role: str) -> tuple[str, str]:
    hasher = PasswordHasher()
    user = auth_service.store.create_user(
        email=email,
        password_hash=hasher.hash_password(_PASSWORD),
        display_name=email,
        org_id=org_id,
        roles=(role,),
        permissions=permissions_for_roles((role,)),
    )
    _record, tokens = auth_service.sign_in(email, _PASSWORD)
    return user.user_id, tokens.access_token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _build_approval_client(
    auth_service: AuthService,
) -> tuple[Any, InMemoryFileRepository, InMemoryFileVectorSink]:
    repository = InMemoryFileRepository()
    vector_sink = InMemoryFileVectorSink()
    app = create_app(
        file_repository=repository,
        file_vector_sink=vector_sink,
        object_storage_adapter=InMemoryObjectStorageAdapter(),
        auth_service=auth_service,
    )
    return TestClient(app), repository, vector_sink


def _seed_one_chunk(vector_sink: InMemoryFileVectorSink, *, org_id: str, user_id: str, file_id: str) -> None:
    chunk = TextChunk(
        text="Escalate P1 incidents to the on-call engineer within 15 minutes.",
        chunk_index=0,
        org_id=org_id,
        user_id=user_id,
        file_id=file_id,
    )
    vector_sink.upsert_chunks((chunk,), ((1.0, 0.0, 0.0),))


def test_http_second_share_request_while_pending_returns_409() -> None:
    # AC-FV10-034
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Approval Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    client, repository, _vector_sink = _build_approval_client(auth_service)
    file_id = "ufile_approval0000000000000000002"
    _seed_file(repository, file_id=file_id, org_id=org.org_id, user_id=owner_id)

    first = client.post(f"/api/v2/files/{file_id}/share-requests", headers=_auth_headers(owner_token))
    second = client.post(f"/api/v2/files/{file_id}/share-requests", headers=_auth_headers(owner_token))

    assert first.status_code == 201
    assert first.json()["data"]["status"] == "pending"
    assert second.status_code == 409


def test_http_submit_share_request_for_a_file_not_owned_returns_403() -> None:
    # NFR-FV10-014: the file is visible to a same-org analyst colleague (a
    # "team" scoped file isn't, but an "org" scoped one already is per
    # FR-FV10-026), so the denial here is a distinguishable 403 — not owned,
    # not an existence question.
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Approval Org")
    owner_id, _owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    _colleague_id, colleague_token = _seed_user(auth_service, org.org_id, "colleague@example.com", "analyst")
    client, repository, _vector_sink = _build_approval_client(auth_service)
    file_id = "ufile_approval0000000000000000004"
    _seed_file(repository, file_id=file_id, org_id=org.org_id, user_id=owner_id, scope="org")

    response = client.post(f"/api/v2/files/{file_id}/share-requests", headers=_auth_headers(colleague_token))

    assert response.status_code == 403


def test_http_submit_share_request_for_an_unknown_file_returns_404() -> None:
    # NFR-FV10-014
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Approval Org")
    _owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    client, _repository, _vector_sink = _build_approval_client(auth_service)

    response = client.post(
        "/api/v2/files/ufile_missing000000000000000001/share-requests", headers=_auth_headers(owner_token)
    )

    assert response.status_code == 404


def test_http_approval_widens_file_access_to_same_role_colleague_but_not_other_roles() -> None:
    # AC-FV10-035
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Approval Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    _colleague_id, colleague_token = _seed_user(auth_service, org.org_id, "colleague@example.com", "analyst")
    _biz_id, biz_token = _seed_user(auth_service, org.org_id, "biz@example.com", "business_user")
    _admin_id, admin_token = _seed_user(auth_service, org.org_id, "admin@example.com", "admin")
    client, repository, _vector_sink = _build_approval_client(auth_service)
    file_id = "ufile_approval0000000000000000003"
    _seed_file(repository, file_id=file_id, org_id=org.org_id, user_id=owner_id)

    before_colleague = client.get(f"/api/v2/files/{file_id}", headers=_auth_headers(colleague_token))
    submit_response = client.post(f"/api/v2/files/{file_id}/share-requests", headers=_auth_headers(owner_token))
    request_id = submit_response.json()["data"]["request_id"]
    approve_response = client.post(
        f"/api/v2/admin/share-requests/{request_id}/approve", headers=_auth_headers(admin_token)
    )
    after_colleague = client.get(f"/api/v2/files/{file_id}", headers=_auth_headers(colleague_token))
    after_biz = client.get(f"/api/v2/files/{file_id}", headers=_auth_headers(biz_token))

    assert before_colleague.status_code == 404
    assert approve_response.status_code == 200
    assert after_colleague.status_code == 200
    # business_user does not share the requester's role, so no
    # FileShareRecord was fanned out to them; a same-org admin is a
    # separate, pre-existing "admin can review any file" access path
    # (FileAccessChecker.check()'s role == "admin" branch, unmodified by
    # this spec) and is intentionally not exercised here.
    assert after_biz.status_code == 404


def test_http_rejection_leaves_the_file_inaccessible_and_creates_no_shares() -> None:
    # AC-FV10-037
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Approval Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    _colleague_id, colleague_token = _seed_user(auth_service, org.org_id, "colleague@example.com", "analyst")
    _admin_id, admin_token = _seed_user(auth_service, org.org_id, "admin@example.com", "admin")
    client, repository, _vector_sink = _build_approval_client(auth_service)
    file_id = "ufile_approval0000000000000000005"
    _seed_file(repository, file_id=file_id, org_id=org.org_id, user_id=owner_id)

    submit_response = client.post(f"/api/v2/files/{file_id}/share-requests", headers=_auth_headers(owner_token))
    request_id = submit_response.json()["data"]["request_id"]
    reject_response = client.post(
        f"/api/v2/admin/share-requests/{request_id}/reject",
        headers=_auth_headers(admin_token),
        json={"reason": "Contains PII"},
    )
    after_reject = client.get(f"/api/v2/files/{file_id}", headers=_auth_headers(colleague_token))

    assert reject_response.status_code == 200
    assert reject_response.json()["data"]["status"] == "rejected"
    assert reject_response.json()["data"]["reason"] == "Contains PII"
    assert after_reject.status_code == 404
    assert repository.shares_for_file(file_id) == ()


def test_http_admin_lists_only_pending_requests_scoped_to_their_org() -> None:
    auth_service = _fresh_auth_service()
    org_a = auth_service.store.create_organization("Org A")
    org_b = auth_service.store.create_organization("Org B")
    owner_a_id, owner_a_token = _seed_user(auth_service, org_a.org_id, "owner_a@example.com", "analyst")
    owner_b_id, owner_b_token = _seed_user(auth_service, org_b.org_id, "owner_b@example.com", "analyst")
    _admin_a_id, admin_a_token = _seed_user(auth_service, org_a.org_id, "admin_a@example.com", "admin")
    client, repository, _vector_sink = _build_approval_client(auth_service)
    file_a = "ufile_approval0000000000000000006"
    file_b = "ufile_approval0000000000000000007"
    _seed_file(repository, file_id=file_a, org_id=org_a.org_id, user_id=owner_a_id)
    _seed_file(repository, file_id=file_b, org_id=org_b.org_id, user_id=owner_b_id)
    client.post(f"/api/v2/files/{file_a}/share-requests", headers=_auth_headers(owner_a_token))
    client.post(f"/api/v2/files/{file_b}/share-requests", headers=_auth_headers(owner_b_token))

    response = client.get(
        "/api/v2/admin/share-requests", headers=_auth_headers(admin_a_token), params={"status": "pending"}
    )

    assert response.status_code == 200
    file_ids = {item["file_id"] for item in response.json()["data"]["items"]}
    assert file_ids == {file_a}


def test_http_full_share_approval_flow_surfaces_rag_evidence_to_fanout_colleague_only() -> None:
    # TC-FV10-124
    auth_service = _fresh_auth_service()
    org = auth_service.store.create_organization("Approval Org")
    owner_id, owner_token = _seed_user(auth_service, org.org_id, "owner@example.com", "analyst")
    _colleague_id, colleague_token = _seed_user(auth_service, org.org_id, "colleague@example.com", "analyst")
    _admin_id, admin_token = _seed_user(auth_service, org.org_id, "admin@example.com", "admin")
    client, repository, vector_sink = _build_approval_client(auth_service)
    file_id = "ufile_approval0000000000000000001"
    _seed_file(repository, file_id=file_id, org_id=org.org_id, user_id=owner_id, file_type="unstructured")
    _seed_one_chunk(vector_sink, org_id=org.org_id, user_id=owner_id, file_id=file_id)

    promote_response = client.post(
        "/api/v2/admin/knowledge/promote-file",
        headers=_auth_headers(admin_token),
        json={"file_id": file_id},
    )
    doc_id = promote_response.json()["data"]["promoted_to_doc_id"]

    submit_response = client.post(f"/api/v2/files/{file_id}/share-requests", headers=_auth_headers(owner_token))
    request_id = submit_response.json()["data"]["request_id"]
    approve_response = client.post(
        f"/api/v2/admin/share-requests/{request_id}/approve", headers=_auth_headers(admin_token)
    )

    question_body = {
        "request_id": "req_share_flow_query0",
        "session_id": "ses_share_flow",
        "user_id": "ignored",
        "role": "analyst",
        "locale": "en",
        "question": "Why should we escalate P1 incidents to the on-call engineer? Please explain.",
    }
    colleague_response = client.post(
        "/api/v2/chat/query", headers=_auth_headers(colleague_token), json=question_body
    )
    admin_response = client.post(
        "/api/v2/chat/query", headers=_auth_headers(admin_token), json={**question_body, "role": "admin"}
    )

    assert promote_response.status_code == 200
    assert submit_response.status_code == 201
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["status"] == "approved"
    colleague_evidence_ids = {
        item["source_id"] for item in colleague_response.json()["data"]["evidence_list"]
    }
    admin_evidence_ids = {item["source_id"] for item in admin_response.json()["data"]["evidence_list"]}
    assert doc_id in colleague_evidence_ids
    assert doc_id not in admin_evidence_ids
