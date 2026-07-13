import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from chatbi.api.http import _load_knowledge_store_from_db  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
from chatbi.api.http import create_app
from chatbi.auth import AuthService, SignUpRequest, TokenService
from chatbi.core.contracts import new_trace_id
from chatbi.embedding_vector_rag import InMemoryVectorStore
from chatbi.files import (
    DocumentNotPromotedError,
    FileNotPromotableError,
    InMemoryFileRepository,
    InMemoryFileVectorSink,
    KnowledgePromotionService,
    NotAuthorizedToPromoteError,
    TextChunk,
    UserUploadedFile,
    connect_psycopg,
)
from chatbi.knowledge import InMemoryKnowledgeStore, RetrievalQuery
from chatbi.migrations import MigrationRunner


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_doc1",
        org_id="org_1",
        user_id="user_1",
        original_name="playbook.pdf",
        file_type="unstructured",
        mime_type="application/pdf",
        size_bytes=2048,
        storage_key="org_1/user_1/ufile_doc1/playbook.pdf",
        content_hash="hash_doc1",
        status="ready",
        scope="user",
        file_group_id="fgrp_1",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        chunk_count=1,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def _seed_one_chunk(vector_source: InMemoryFileVectorSink, file_id: str) -> None:
    chunk = TextChunk(
        text="Escalate P1 incidents to the on-call engineer within 15 minutes.",
        chunk_index=0,
        org_id="org_1",
        user_id="user_1",
        file_id=file_id,
    )
    vector_source.upsert_chunks((chunk,), ((1.0, 0.0, 0.0),))


def _build_service(
    repository: InMemoryFileRepository,
    vector_store: InMemoryVectorStore,
    vector_source: InMemoryFileVectorSink,
) -> KnowledgePromotionService:
    return KnowledgePromotionService(
        repository=repository, vector_store=vector_store, vector_source=vector_source
    )


def test_promote_creates_document_with_source_type_user_promoted() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = _build_service(repository, vector_store, vector_source)

    promoted = service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    document = vector_store.get_document(promoted.promoted_to_doc_id)  # type: ignore[arg-type]
    assert document is not None
    assert document.source_type == "user_promoted"
    assert document.org_id == "org_1"


def test_promote_sets_promoted_to_doc_id_on_source_file() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = _build_service(repository, vector_store, vector_source)

    promoted = service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    assert promoted.promoted_to_doc_id is not None
    assert promoted.promoted_to_doc_id.startswith("doc_")
    assert repository.get("ufile_doc1").promoted_to_doc_id == promoted.promoted_to_doc_id  # type: ignore[union-attr]


def test_promote_makes_the_document_immediately_searchable_by_rag_agent_runner() -> None:
    """RagAgentRunner reads InMemoryKnowledgeStore, not the VectorStore above.

    Promoting must reach that store directly so a promoted file is findable
    by a real chat query in the same process, without waiting for a restart
    that would reload knowledge_store from Postgres. Per Spec FV10.1, the
    promoted document is private to its uploader (``_file()``'s user_id,
    "user_1"), so the retrieving user must match to see it.
    """

    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    live_knowledge_store = InMemoryKnowledgeStore()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = KnowledgePromotionService(
        repository=repository,
        vector_store=vector_store,
        vector_source=vector_source,
        live_knowledge_store=live_knowledge_store,
    )

    service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    result = live_knowledge_store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="user_1",
        )
    )
    assert len(result.evidence_list) == 1
    assert "on-call engineer" in result.evidence_list[0].snippet


def test_promote_stamps_owner_user_id_from_the_uploading_user() -> None:
    """FR-FV10-040: owner_user_id comes from the file's uploader, not the
    admin performing the promotion.
    """

    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    live_knowledge_store = InMemoryKnowledgeStore()
    repository.save(_file(user_id="user_1"))
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = KnowledgePromotionService(
        repository=repository,
        vector_store=vector_store,
        vector_source=vector_source,
        live_knowledge_store=live_knowledge_store,
    )

    promoted = service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    document = live_knowledge_store._documents_by_source_id[  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        promoted.promoted_to_doc_id  # type: ignore[index]
    ]
    assert document.owner_user_id == "user_1"


def test_promoted_document_is_not_retrievable_by_a_different_user() -> None:
    """FR-FV10-039/NFR-FV10-011: a colleague in the same org must not see
    another user's promoted-but-not-shared document.
    """

    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    live_knowledge_store = InMemoryKnowledgeStore()
    repository.save(_file(user_id="user_1"))
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = KnowledgePromotionService(
        repository=repository,
        vector_store=vector_store,
        vector_source=vector_source,
        live_knowledge_store=live_knowledge_store,
    )

    service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    result = live_knowledge_store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="user_2",
        )
    )
    assert result.evidence_list == ()


def test_promote_persists_owner_user_id_into_postgres_live() -> None:
    """TC-FV10-113: promote_file() must write owner_user_id into the real
    knowledge.documents row, not just the in-process store, so it survives
    a restart (see _load_knowledge_store_from_db).
    """

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for live PostgreSQL knowledge promotion integration.")

    connection = connect_psycopg(database_url)
    try:
        MigrationRunner(connection).apply_base_migration()

        repository = InMemoryFileRepository()
        vector_store = InMemoryVectorStore()
        vector_source = InMemoryFileVectorSink()
        file_id = f"ufile_live_{uuid4().hex[:16]}"
        repository.save(_file(file_id=file_id, user_id="user_live_1"))
        _seed_one_chunk(vector_source, file_id)
        service = KnowledgePromotionService(
            repository=repository,
            vector_store=vector_store,
            vector_source=vector_source,
            knowledge_connection=connection,
        )

        promoted = service.promote_file(file_id, role="admin", org_id="org_1")

        with connection.cursor() as cur:
            cur.execute(
                "SELECT owner_user_id FROM knowledge.documents WHERE source_id = %s",
                (promoted.promoted_to_doc_id,),
            )
            row = cur.fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row[0] == "user_live_1"


def test_reload_from_db_preserves_owner_user_id_after_restart() -> None:
    """AC-FV10-033: a fresh InMemoryKnowledgeStore rebuilt from Postgres
    (simulating a process restart via _load_knowledge_store_from_db) must
    retain owner_user_id on a document promoted in a previous process
    lifetime, so the isolation guarantee survives a restart.
    """

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for live PostgreSQL knowledge promotion integration.")

    connection = connect_psycopg(database_url)
    try:
        MigrationRunner(connection).apply_base_migration()

        repository = InMemoryFileRepository()
        vector_store = InMemoryVectorStore()
        vector_source = InMemoryFileVectorSink()
        file_id = f"ufile_live_{uuid4().hex[:16]}"
        repository.save(_file(file_id=file_id, user_id="user_live_2"))
        _seed_one_chunk(vector_source, file_id)
        service = KnowledgePromotionService(
            repository=repository,
            vector_store=vector_store,
            vector_source=vector_source,
            knowledge_connection=connection,
        )
        promoted = service.promote_file(file_id, role="admin", org_id="org_1")
    finally:
        connection.close()

    reloaded_store = _load_knowledge_store_from_db(connect_psycopg, database_url)

    owner_result = reloaded_store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="user_live_2",
        )
    )
    stranger_result = reloaded_store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="user_live_3",
        )
    )

    assert promoted.promoted_to_doc_id in {item.source_id for item in owner_result.evidence_list}
    assert promoted.promoted_to_doc_id not in {item.source_id for item in stranger_result.evidence_list}


def test_demote_succeeds_even_if_the_ephemeral_vector_store_lost_the_document() -> None:
    """Simulates a backend restart: vector_store is a fresh, empty instance,
    but the file's promoted_to_doc_id survived in the (Postgres-backed)
    repository. Demote must not depend on the ephemeral store's memory.
    """

    repository = InMemoryFileRepository()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = KnowledgePromotionService(
        repository=repository,
        vector_store=InMemoryVectorStore(),
        vector_source=vector_source,
    )
    promoted = service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    # Fresh vector_store simulates a process restart wiping the ephemeral store.
    service_after_restart = KnowledgePromotionService(
        repository=repository,
        vector_store=InMemoryVectorStore(),
        vector_source=vector_source,
    )

    demoted = service_after_restart.demote_document(
        promoted.promoted_to_doc_id,  # type: ignore[arg-type]
        role="admin",
        org_id="org_1",
    )

    assert demoted.promoted_to_doc_id is None


def test_demote_removes_the_document_from_the_live_knowledge_store() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    live_knowledge_store = InMemoryKnowledgeStore()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = KnowledgePromotionService(
        repository=repository,
        vector_store=vector_store,
        vector_source=vector_source,
        live_knowledge_store=live_knowledge_store,
    )
    promoted = service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    service.demote_document(promoted.promoted_to_doc_id, role="admin", org_id="org_1")  # type: ignore[arg-type]

    result = live_knowledge_store.retrieve(
        RetrievalQuery(
            question="Escalate P1 incidents to the on-call engineer",
            requesting_user_id="user_1",
        )
    )
    assert len(result.evidence_list) == 0


def test_promoted_document_is_retrievable_by_other_analysts_without_file_ids() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = _build_service(repository, vector_store, vector_source)
    service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    evidence = vector_store.search(
        trace_id=new_trace_id(),
        org_id="org_1",
        query_vector=(1.0, 0.0, 0.0),
        permission_tags=(),
        limit=5,
    )

    assert len(evidence) == 1
    assert "on-call engineer" in evidence[0].text


def test_demote_removes_evidence_from_other_analysts_queries() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = _build_service(repository, vector_store, vector_source)
    promoted = service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    service.demote_document(promoted.promoted_to_doc_id, role="admin", org_id="org_1")  # type: ignore[arg-type]

    evidence = vector_store.search(
        trace_id=new_trace_id(),
        org_id="org_1",
        query_vector=(1.0, 0.0, 0.0),
        permission_tags=(),
        limit=5,
    )
    assert evidence == ()


def test_demote_clears_promoted_to_doc_id_on_source_file() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = _build_service(repository, vector_store, vector_source)
    promoted = service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    service.demote_document(promoted.promoted_to_doc_id, role="admin", org_id="org_1")  # type: ignore[arg-type]

    assert repository.get("ufile_doc1").promoted_to_doc_id is None  # type: ignore[union-attr]


def test_non_admin_cannot_promote() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    service = _build_service(repository, vector_store, vector_source)

    with pytest.raises(NotAuthorizedToPromoteError):
        service.promote_file("ufile_doc1", role="analyst", org_id="org_1")


def test_non_admin_cannot_demote() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    service = _build_service(repository, vector_store, vector_source)

    with pytest.raises(NotAuthorizedToPromoteError):
        service.demote_document("doc_anything", role="business_user", org_id="org_1")


def test_promote_rejects_structured_files() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(
        _file(
            file_type="structured",
            mime_type="text/csv",
            schema_json={"columns": []},
            row_count=0,
            chunk_count=None,
        )
    )
    service = _build_service(repository, vector_store, vector_source)

    with pytest.raises(FileNotPromotableError):
        service.promote_file("ufile_doc1", role="admin", org_id="org_1")


def test_promote_rejects_files_not_yet_ready() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file(status="indexing", chunk_count=None))
    service = _build_service(repository, vector_store, vector_source)

    with pytest.raises(FileNotPromotableError):
        service.promote_file("ufile_doc1", role="admin", org_id="org_1")


def test_promote_rejects_a_ready_file_with_no_chunks_in_the_vector_source() -> None:
    # The in-process vector source does not survive a restart (see
    # promotion.py's module docstring) — a ready file whose chunks were
    # produced in a prior process lifetime has nothing to copy. Promoting
    # anyway would silently create a permanently-empty knowledge document
    # instead of failing loudly, so this must raise.
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    live_knowledge_store = InMemoryKnowledgeStore()
    repository.save(_file())
    service = KnowledgePromotionService(
        repository=repository,
        vector_store=vector_store,
        vector_source=vector_source,
        live_knowledge_store=live_knowledge_store,
    )

    with pytest.raises(FileNotPromotableError):
        service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    # No half-created document anywhere — the check runs before any write.
    assert vector_store._documents_by_id == {}  # noqa: SLF001
    assert live_knowledge_store._documents_by_source_id == {}  # noqa: SLF001
    assert repository.get("ufile_doc1").promoted_to_doc_id is None  # type: ignore[union-attr]


def test_demote_unknown_document_raises() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    service = _build_service(repository, vector_store, vector_source)

    with pytest.raises(DocumentNotPromotedError):
        service.demote_document("doc_missing", role="admin", org_id="org_1")


def test_admin_cannot_promote_a_file_from_a_different_org() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = _build_service(repository, vector_store, vector_source)

    with pytest.raises(FileNotPromotableError):
        service.promote_file("ufile_doc1", role="admin", org_id="org_2")


def test_admin_cannot_demote_a_document_from_a_different_org() -> None:
    repository = InMemoryFileRepository()
    vector_store = InMemoryVectorStore()
    vector_source = InMemoryFileVectorSink()
    repository.save(_file())
    _seed_one_chunk(vector_source, "ufile_doc1")
    service = _build_service(repository, vector_store, vector_source)
    promoted = service.promote_file("ufile_doc1", role="admin", org_id="org_1")

    with pytest.raises(DocumentNotPromotedError):
        service.demote_document(promoted.promoted_to_doc_id, role="admin", org_id="org_2")  # type: ignore[arg-type]

    # The promotion must survive the failed cross-org attempt untouched.
    evidence = vector_store.search(
        trace_id=new_trace_id(),
        org_id="org_1",
        query_vector=(1.0, 0.0, 0.0),
        permission_tags=(),
        limit=5,
    )
    assert len(evidence) == 1


def _admin_auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _http_ready_file(**overrides: object) -> UserUploadedFile:
    fields: dict[str, object] = dict(
        file_id="ufile_httpdoc0000000000000000001",
        org_id="org_test",
        user_id="u_001",
        original_name="runbook.pdf",
        file_type="unstructured",
        mime_type="application/pdf",
        size_bytes=2048,
        storage_key="org_test/u_001/ufile_httpdoc0000000000000000001/runbook.pdf",
        content_hash="hash_httpdoc",
        status="ready",
        scope="user",
        file_group_id="fgrp_http",
        version_number=1,
        is_latest=True,
        created_at=_now(),
        chunk_count=1,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def _build_http_client(
    repository: InMemoryFileRepository, vector_sink: InMemoryFileVectorSink
) -> Any:
    return TestClient(
        create_app(file_repository=repository, file_vector_sink=vector_sink)
    )


def test_http_promote_then_demote_round_trips_promoted_to_doc_id() -> None:
    repository = InMemoryFileRepository()
    vector_sink = InMemoryFileVectorSink()
    repository.save(_http_ready_file())
    _seed_one_chunk(vector_sink, "ufile_httpdoc0000000000000000001")
    client = _build_http_client(repository, vector_sink)

    promote_response = client.post(
        "/api/v2/admin/knowledge/promote-file",
        headers=_admin_auth_headers(),
        json={"file_id": "ufile_httpdoc0000000000000000001"},
    )
    doc_id = promote_response.json()["data"]["promoted_to_doc_id"]
    file_after_promote = client.get(
        "/api/v2/files/ufile_httpdoc0000000000000000001", headers=_admin_auth_headers()
    )

    demote_response = client.delete(
        f"/api/v2/admin/knowledge/{doc_id}",
        headers=_admin_auth_headers(),
        params={"mode": "demote"},
    )
    file_after_demote = client.get(
        "/api/v2/files/ufile_httpdoc0000000000000000001", headers=_admin_auth_headers()
    )

    assert promote_response.status_code == 200
    assert doc_id.startswith("doc_")
    assert file_after_promote.json()["data"]["promoted_to_doc_id"] == doc_id
    assert demote_response.status_code == 204
    assert file_after_demote.json()["data"]["promoted_to_doc_id"] is None


def test_http_non_admin_calling_promote_endpoint_returns_403() -> None:
    auth_service = AuthService(token_service=TokenService(secret="test-secret"))
    _user, tokens = auth_service.sign_up(
        SignUpRequest(
            email="analyst_biz@example.com",
            password="correct horse battery staple",
            display_name="Business User",
        )
    )
    repository = InMemoryFileRepository()
    vector_sink = InMemoryFileVectorSink()
    repository.save(_http_ready_file())
    client: Any = TestClient(
        create_app(
            file_repository=repository, file_vector_sink=vector_sink, auth_service=auth_service
        )
    )

    response = client.post(
        "/api/v2/admin/knowledge/promote-file",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
        json={"file_id": "ufile_httpdoc0000000000000000001"},
    )

    assert response.status_code == 403


def test_http_promote_structured_file_returns_422() -> None:
    repository = InMemoryFileRepository()
    vector_sink = InMemoryFileVectorSink()
    repository.save(
        _http_ready_file(
            file_type="structured",
            mime_type="text/csv",
            schema_json={"columns": []},
            row_count=0,
            chunk_count=None,
        )
    )
    client = _build_http_client(repository, vector_sink)

    response = client.post(
        "/api/v2/admin/knowledge/promote-file",
        headers=_admin_auth_headers(),
        json={"file_id": "ufile_httpdoc0000000000000000001"},
    )

    assert response.status_code == 422


def test_http_demote_without_mode_query_param_returns_422() -> None:
    repository = InMemoryFileRepository()
    vector_sink = InMemoryFileVectorSink()
    client = _build_http_client(repository, vector_sink)

    response = client.delete(
        "/api/v2/admin/knowledge/doc_anything", headers=_admin_auth_headers()
    )

    assert response.status_code == 422


def test_http_demote_unknown_document_returns_404() -> None:
    repository = InMemoryFileRepository()
    vector_sink = InMemoryFileVectorSink()
    client = _build_http_client(repository, vector_sink)

    response = client.delete(
        "/api/v2/admin/knowledge/doc_missing",
        headers=_admin_auth_headers(),
        params={"mode": "demote"},
    )

    assert response.status_code == 404


def _rag_query_body(*, user_id: str, request_id: str, session_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "session_id": session_id,
        "user_id": user_id,
        "role": "analyst",
        "locale": "en",
        "question": "Why should we escalate P1 incidents to the on-call engineer? Please explain.",
    }


def test_http_promoted_document_surfaces_in_evidence_for_the_promoting_user() -> None:
    """TC-FV10-114: analyst_a promotes a file; a /api/v2/chat/query from
    analyst_a (no file_ids, a why/explain question) surfaces the promoted
    document in evidence_list.
    """

    repository = InMemoryFileRepository()
    vector_sink = InMemoryFileVectorSink()
    repository.save(_http_ready_file(user_id="analyst_a"))
    _seed_one_chunk(vector_sink, "ufile_httpdoc0000000000000000001")
    client = _build_http_client(repository, vector_sink)

    promote_response = client.post(
        "/api/v2/admin/knowledge/promote-file",
        headers=_admin_auth_headers(),
        json={"file_id": "ufile_httpdoc0000000000000000001"},
    )
    doc_id = promote_response.json()["data"]["promoted_to_doc_id"]

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_rag_query_body(
            user_id="analyst_a", request_id="req_analyst_a_rag0", session_id="ses_analyst_a"
        ),
    )

    assert promote_response.status_code == 200
    assert response.status_code == 200
    evidence_ids = {item["source_id"] for item in response.json()["data"]["evidence_list"]}
    assert doc_id in evidence_ids


def test_http_promoted_document_is_hidden_from_a_different_analyst() -> None:
    """TC-FV10-115: the same question, asked by analyst_b in the same org,
    does NOT surface analyst_a's promoted document; seeded baseline evidence
    (there is none seeded in this in-memory test app) is unaffected either way.
    """

    repository = InMemoryFileRepository()
    vector_sink = InMemoryFileVectorSink()
    repository.save(_http_ready_file(user_id="analyst_a"))
    _seed_one_chunk(vector_sink, "ufile_httpdoc0000000000000000001")
    client = _build_http_client(repository, vector_sink)

    promote_response = client.post(
        "/api/v2/admin/knowledge/promote-file",
        headers=_admin_auth_headers(),
        json={"file_id": "ufile_httpdoc0000000000000000001"},
    )
    doc_id = promote_response.json()["data"]["promoted_to_doc_id"]

    response = client.post(
        "/api/v2/chat/query",
        headers=_admin_auth_headers(),
        json=_rag_query_body(
            user_id="analyst_b", request_id="req_analyst_b_rag0", session_id="ses_analyst_b"
        ),
    )

    assert response.status_code == 200
    evidence_ids = {item["source_id"] for item in response.json()["data"]["evidence_list"]}
    assert doc_id not in evidence_ids
