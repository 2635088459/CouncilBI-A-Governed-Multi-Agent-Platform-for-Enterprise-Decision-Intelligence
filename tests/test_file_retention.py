from datetime import datetime, timedelta, timezone

from chatbi.embedding_vector_rag import InMemoryVectorStore
from chatbi.files import (
    InMemoryFileRepository,
    InMemoryFileVectorSink,
    KnowledgePromotionService,
    RetentionWorker,
    UserUploadedFile,
)
from chatbi.knowledge import InMemoryKnowledgeStore, KnowledgeDocument, RetrievalQuery


_FIXED_NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return _FIXED_NOW


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
        scope="session",
        session_id="ses_1",
        file_group_id="fgrp_1",
        version_number=1,
        is_latest=True,
        created_at=_FIXED_NOW - timedelta(days=100),
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}]},
        row_count=10,
    )
    fields.update(overrides)
    return UserUploadedFile(**fields)  # type: ignore[arg-type]


def _promotion_service(
    repository: InMemoryFileRepository, live_knowledge_store: InMemoryKnowledgeStore
) -> KnowledgePromotionService:
    return KnowledgePromotionService(
        repository=repository,
        vector_store=InMemoryVectorStore(),
        vector_source=InMemoryFileVectorSink(),
        live_knowledge_store=live_knowledge_store,
    )


def test_session_scoped_file_archives_24_hours_after_last_activity() -> None:
    repository = InMemoryFileRepository()
    expired_file = _file(
        file_id="ufile_expired",
        scope="session",
        last_accessed_at=_FIXED_NOW - timedelta(hours=24, seconds=1),
    )
    fresh_file = _file(
        file_id="ufile_fresh",
        scope="session",
        file_group_id="fgrp_2",
        last_accessed_at=_FIXED_NOW - timedelta(hours=23),
    )
    repository.save(expired_file)
    repository.save(fresh_file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    worker.run()

    archived = repository.get("ufile_expired")
    fresh = repository.get("ufile_fresh")
    assert archived is not None and archived.archived_at == _FIXED_NOW
    assert fresh is not None and fresh.archived_at is None


def test_user_scoped_file_archives_10_days_after_last_access() -> None:
    # TC-FV10-125 / FR-FV10-045: the shortened 10-day threshold, was 30.
    repository = InMemoryFileRepository()
    expired_file = _file(
        file_id="ufile_expired",
        scope="user",
        session_id=None,
        last_accessed_at=_FIXED_NOW - timedelta(days=10, seconds=1),
    )
    fresh_file = _file(
        file_id="ufile_fresh",
        scope="user",
        session_id=None,
        file_group_id="fgrp_2",
        last_accessed_at=_FIXED_NOW - timedelta(days=9),
    )
    repository.save(expired_file)
    repository.save(fresh_file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    worker.run()

    archived = repository.get("ufile_expired")
    fresh = repository.get("ufile_fresh")
    assert archived is not None and archived.archived_at == _FIXED_NOW
    assert fresh is not None and fresh.archived_at is None


def test_user_scoped_file_does_not_archive_at_9_days() -> None:
    # TC-FV10-126
    repository = InMemoryFileRepository()
    file = _file(
        scope="user",
        session_id=None,
        last_accessed_at=_FIXED_NOW - timedelta(days=9),
    )
    repository.save(file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    worker.run()

    assert repository.get("ufile_abc123").archived_at is None  # type: ignore[union-attr]


def test_team_scoped_file_archives_at_60_days_not_90() -> None:
    # TC-FV10-127 / FR-FV10-045: the shortened 60-day threshold, was 90.
    repository = InMemoryFileRepository()
    archives_at_60 = _file(
        file_id="ufile_60",
        scope="team",
        session_id=None,
        last_accessed_at=_FIXED_NOW - timedelta(days=60, seconds=1),
    )
    survives_at_59 = _file(
        file_id="ufile_59",
        scope="team",
        session_id=None,
        file_group_id="fgrp_2",
        last_accessed_at=_FIXED_NOW - timedelta(days=59),
    )
    repository.save(archives_at_60)
    repository.save(survives_at_59)
    worker = RetentionWorker(repository=repository, clock=_clock)

    worker.run()

    archived = repository.get("ufile_60")
    still_active = repository.get("ufile_59")
    assert archived is not None and archived.archived_at == _FIXED_NOW
    assert still_active is not None and still_active.archived_at is None


def test_org_scoped_files_are_never_archived_by_retention() -> None:
    repository = InMemoryFileRepository()
    file = _file(scope="org", session_id=None, last_accessed_at=_FIXED_NOW - timedelta(days=1000))
    repository.save(file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    worker.run()

    assert repository.get("ufile_abc123").archived_at is None  # type: ignore[union-attr]


def test_expired_file_falls_back_to_created_at_when_never_accessed() -> None:
    repository = InMemoryFileRepository()
    file = _file(
        scope="session",
        last_accessed_at=None,
        created_at=_FIXED_NOW - timedelta(hours=25),
    )
    repository.save(file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    worker.run()

    assert repository.get("ufile_abc123").archived_at == _FIXED_NOW  # type: ignore[union-attr]


def test_archiving_preserves_the_metadata_row_and_does_not_soft_delete() -> None:
    # FR-FV10-046: archiving must not purge storage or the metadata row —
    # only archived_at is set; deleted_at stays untouched.
    repository = InMemoryFileRepository()
    file = _file(scope="session", last_accessed_at=_FIXED_NOW - timedelta(hours=25))
    repository.save(file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    worker.run()

    archived = repository.get("ufile_abc123")
    assert archived is not None
    assert archived.archived_at == _FIXED_NOW
    assert archived.deleted_at is None


def test_archived_file_no_longer_appears_in_owner_listing_but_stays_in_active_scan() -> None:
    repository = InMemoryFileRepository()
    file = _file(scope="session", last_accessed_at=_FIXED_NOW - timedelta(hours=25))
    repository.save(file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    worker.run()

    # Archived files do not show up in the owner's own listing (§3)...
    assert repository.list_by_owner("org_1", "user_1") == ()
    # ...but list_active() (deleted_at IS NULL) still finds it, since a
    # repeated sweep needs to see it in order to recognize and skip it.
    assert [f.file_id for f in repository.list_active()] == ["ufile_abc123"]


def test_run_returns_the_records_it_archived() -> None:
    repository = InMemoryFileRepository()
    file = _file(scope="session", last_accessed_at=_FIXED_NOW - timedelta(hours=25))
    repository.save(file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    archived = worker.run()

    assert [f.file_id for f in archived] == ["ufile_abc123"]
    assert archived[0].archived_at == _FIXED_NOW


def test_running_the_sweep_twice_does_not_reprocess_an_already_archived_file() -> None:
    # TC-FV10-128 / NFR-FV10-015
    repository = InMemoryFileRepository()
    file = _file(scope="session", last_accessed_at=_FIXED_NOW - timedelta(hours=25))
    repository.save(file)
    worker = RetentionWorker(repository=repository, clock=_clock)

    first_run = worker.run()
    second_run = worker.run()

    assert [f.file_id for f in first_run] == ["ufile_abc123"]
    assert second_run == ()
    assert repository.get("ufile_abc123").archived_at == _FIXED_NOW  # type: ignore[union-attr]


def test_archiving_a_promoted_file_removes_its_rag_content_and_clears_promoted_to_doc_id() -> None:
    # TC-FV10-132 / FR-FV10-048 / AC-FV10-041
    repository = InMemoryFileRepository()
    live_knowledge_store = InMemoryKnowledgeStore()
    live_knowledge_store.ingest_document(
        KnowledgeDocument(
            source_id="doc_promoted_1",
            title="Promoted runbook",
            doc_type="user_promoted",
            publish_time=_FIXED_NOW,
            owner_user_id="user_1",
        ),
        "Escalate P1 incidents to the on-call engineer within 15 minutes.",
    )
    promotion_service = _promotion_service(repository, live_knowledge_store)
    file = _file(
        scope="user",
        session_id=None,
        last_accessed_at=_FIXED_NOW - timedelta(days=10, seconds=1),
        promoted_to_doc_id="doc_promoted_1",
    )
    repository.save(file)
    worker = RetentionWorker(
        repository=repository, knowledge_promotion_service=promotion_service, clock=_clock
    )

    before = live_knowledge_store.retrieve(
        RetrievalQuery(question="Escalate P1 incidents", requesting_user_id="user_1")
    )

    worker.run()

    after = live_knowledge_store.retrieve(
        RetrievalQuery(question="Escalate P1 incidents", requesting_user_id="user_1")
    )
    archived = repository.get("ufile_abc123")
    assert tuple(item.source_id for item in before.evidence_list) == ("doc_promoted_1",)
    assert after.evidence_list == ()
    assert archived is not None
    assert archived.promoted_to_doc_id is None
    assert archived.archived_at == _FIXED_NOW


def test_archiving_a_non_promoted_file_does_not_touch_the_knowledge_store() -> None:
    repository = InMemoryFileRepository()
    live_knowledge_store = InMemoryKnowledgeStore()
    promotion_service = _promotion_service(repository, live_knowledge_store)
    file = _file(scope="session", last_accessed_at=_FIXED_NOW - timedelta(hours=25))
    repository.save(file)
    worker = RetentionWorker(
        repository=repository, knowledge_promotion_service=promotion_service, clock=_clock
    )

    worker.run()  # must not raise even though promoted_to_doc_id is None

    archived = repository.get("ufile_abc123")
    assert archived is not None
    assert archived.archived_at == _FIXED_NOW
