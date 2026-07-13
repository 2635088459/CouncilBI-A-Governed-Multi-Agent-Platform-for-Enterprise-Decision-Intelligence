"""FileShareApprovalService: the Spec FV10.2 analyst-requested,
admin-approved sharing workflow.

Replaces admin-initiated file promotion with a flow where the file owner
requests sharing and an admin approves or rejects it. Approval fans a single
request out into one ordinary ``FileShareRecord`` per colleague who shares
the requester's ``org_id`` and role — "exactly as if the uploader had shared
with each of them individually via the existing point-to-point share
mechanism" (see the source design). ``FileAccessChecker`` needs no changes
at all: its existing ``scope == "team"`` + active-share branch already
grants access once these records exist.

RAG-visibility widening (FR-FV10-043) is not a separate step here. Spec
FV10.1's ``InMemoryKnowledgeStore`` resolves a promoted document's extra
visibility by asking "does this file have an active share grant for this
user" (see ``file_share_visibility_resolver`` below), so simply creating the
fan-out ``FileShareRecord``s already widens RAG visibility for any promoted
document derived from this file — whether the share came from this bulk
approval flow or the older point-to-point endpoint.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from chatbi.auth import AuthStore
from chatbi.files.access import new_share_id
from chatbi.files.contracts import FileShareRecord, FileShareRequest, UserUploadedFile
from chatbi.files.repository import FileRepository
from chatbi.knowledge import KnowledgeDocument


class FileNotShareableError(Exception):
    """Raised when the target file does not exist (or is invisible to the caller)."""


class NotFileOwnerError(Exception):
    """Raised when a non-owner attempts to request sharing for a file."""


class PendingShareRequestExistsError(Exception):
    """Raised when a file already has an active ``pending`` share request (FR-FV10-041)."""


class ShareRequestNotFoundError(Exception):
    """Raised when a request_id does not resolve within the admin's org."""


class ShareRequestNotPendingError(Exception):
    """Raised when approve/reject targets a request that was already decided."""


def new_share_request_id() -> str:
    return f"req_share_{uuid4().hex}"


class FileShareApprovalService:
    """Submit, approve, and reject Spec FV10.2 file share requests."""

    def __init__(self, *, repository: FileRepository, auth_store: AuthStore) -> None:
        self._repository = repository
        self._auth_store = auth_store

    def submit_request(
        self,
        file_id: str,
        *,
        requester_user_id: str,
        requester_org_id: str,
        requester_role: str,
    ) -> FileShareRequest:
        file = self._repository.get(file_id)
        if file is None or file.deleted_at is not None or file.org_id != requester_org_id:
            raise FileNotShareableError(file_id)
        if file.user_id != requester_user_id:
            raise NotFileOwnerError(file_id)
        if self._repository.pending_share_request_for_file(file_id) is not None:
            raise PendingShareRequestExistsError(file_id)

        request = FileShareRequest(
            request_id=new_share_request_id(),
            file_id=file_id,
            requested_by=requester_user_id,
            org_id=requester_org_id,
            role=requester_role,
            status="pending",
            requested_at=datetime.now(timezone.utc),
        )
        self._repository.save_share_request(request)
        return request

    def approve(
        self,
        request_id: str,
        *,
        admin_user_id: str,
        admin_org_id: str,
    ) -> FileShareRequest:
        request = self._pending_request_in_org(request_id, admin_org_id)

        fanout_user_ids = [
            user.user_id
            for user in self._auth_store.list_users_by_org_and_role(request.org_id, request.role)
            if user.user_id != request.requested_by
        ]
        now = datetime.now(timezone.utc)
        shares = tuple(
            FileShareRecord(
                share_id=new_share_id(),
                file_id=request.file_id,
                granted_by=request.requested_by,
                granted_to=user_id,
                created_at=now,
            )
            for user_id in fanout_user_ids
        )
        # NFR-FV10-013: one atomic write for the whole fan-out — either every
        # matching user gets a FileShareRecord, or (on failure) none do.
        self._repository.save_shares(shares)

        approved = replace(request, status="approved", decided_by=admin_user_id, decided_at=now)
        self._repository.save_share_request(approved)
        return approved

    def reject(
        self,
        request_id: str,
        *,
        admin_user_id: str,
        admin_org_id: str,
        reason: str | None = None,
    ) -> FileShareRequest:
        request = self._pending_request_in_org(request_id, admin_org_id)
        rejected = replace(
            request,
            status="rejected",
            decided_by=admin_user_id,
            decided_at=datetime.now(timezone.utc),
            reason=reason,
        )
        self._repository.save_share_request(rejected)
        return rejected

    def _pending_request_in_org(self, request_id: str, org_id: str) -> FileShareRequest:
        request = self._repository.share_request_by_id(request_id)
        if request is None or request.org_id != org_id:
            raise ShareRequestNotFoundError(request_id)
        if request.status != "pending":
            raise ShareRequestNotPendingError(request_id)
        return request


def file_share_visibility_resolver(
    repository: FileRepository,
) -> Callable[[KnowledgeDocument], frozenset[str]]:
    """Build the FR-FV10-039 ``shared_visibility()`` hook for a knowledge store.

    A promoted ``KnowledgeDocument.source_id`` is the same ``document_id``
    stamped onto its source file's ``promoted_to_doc_id`` (see
    ``KnowledgePromotionService.promote_file``), so visibility is derived by
    walking back to that file and reading its active ``FileShareRecord``s —
    no separate widening state to keep in sync.
    """

    def resolve(document: KnowledgeDocument) -> frozenset[str]:
        source_file = _promoted_source_file(repository, document.source_id)
        if source_file is None:
            return frozenset()
        return frozenset(
            share.granted_to
            for share in repository.shares_for_file(source_file.file_id)
            if share.is_active
        )

    return resolve


def _promoted_source_file(repository: FileRepository, doc_id: str) -> UserUploadedFile | None:
    for file in repository.list_active():
        if file.promoted_to_doc_id == doc_id:
            return file
    return None
