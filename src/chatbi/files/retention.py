"""RetentionWorker: the Spec FV10.3 archival sweep (supersedes FR-FV10-032).

Runs at least once a day and archives files by scope: session-scoped files
24 hours after last activity (unchanged), user-scoped files 10 days after
last access (was 30), team-scoped files 60 days after last access (was 90).
Archiving keeps the file's object-storage bytes and Postgres metadata row
intact — it only sets ``archived_at`` and (if the file had been promoted)
removes its live RAG content. This worker never deletes or purges anything;
the only purge in this feature is the dedup purge on re-upload, handled by
``purge_duplicate_archived_file`` below. ``org``-scoped files are not swept
here — the spec never defined an org-scope expiry rule.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from chatbi.files.contracts import FileScope, UserUploadedFile
from chatbi.files.promotion import KnowledgePromotionService
from chatbi.files.repository import FileRepository
from chatbi.files.storage import ObjectStorageAdapter, parquet_storage_key


RETENTION_THRESHOLDS: dict[FileScope, timedelta] = {
    "session": timedelta(hours=24),
    "user": timedelta(days=10),
    "team": timedelta(days=60),
}


class RetentionWorker:
    """Archive files that have outlived their scope's retention window."""

    def __init__(
        self,
        *,
        repository: FileRepository,
        knowledge_promotion_service: KnowledgePromotionService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._knowledge_promotion_service = knowledge_promotion_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self) -> tuple[UserUploadedFile, ...]:
        now = self._clock()
        archived_records: list[UserUploadedFile] = []
        for file in self._repository.list_active():
            # NFR-FV10-015: an already-archived file stays in list_active()
            # (archiving does not set deleted_at) — skip it so a repeated
            # sweep never re-processes it or re-stamps archived_at.
            if file.archived_at is not None:
                continue
            if not self._is_expired(file, now):
                continue
            if file.promoted_to_doc_id is not None and self._knowledge_promotion_service is not None:
                self._knowledge_promotion_service.remove_from_live_rag(file.promoted_to_doc_id)
            archived = replace(file, archived_at=now, promoted_to_doc_id=None)
            self._repository.save(archived)
            archived_records.append(archived)
        return tuple(archived_records)

    def _is_expired(self, file: UserUploadedFile, now: datetime) -> bool:
        threshold = RETENTION_THRESHOLDS.get(file.scope)
        if threshold is None:
            return False
        reference_time = file.last_accessed_at or file.created_at
        return now - reference_time >= threshold


def purge_duplicate_archived_file(
    *,
    repository: FileRepository,
    storage: ObjectStorageAdapter,
    file: UserUploadedFile,
) -> None:
    """FR-FV10-049: irreversibly delete an archived duplicate's bytes and row.

    Called from the upload path when a new upload's content hash matches an
    archived file owned by the same user — the only purge this feature ever
    performs, and only because the user just proved (by re-uploading the
    identical bytes) that the old archived copy is no longer needed.
    """

    storage.delete_object(file.storage_key)
    if file.file_type == "structured":
        storage.delete_object(parquet_storage_key(file.storage_key))
    repository.hard_delete(file.file_id)
