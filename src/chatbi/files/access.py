"""FileAccessChecker: the section 6.14 access decision matrix.

FR-FV10-036 requires every denial to surface as HTTP 404, never 403, so a
request for another user's file_id cannot be distinguished from a request
for a file_id that simply does not exist (NFR-FV10-005). This module only
returns the ALLOW/DENY decision; mapping DENY to a 404 response is the API
layer's job.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Sequence
from uuid import uuid4

from chatbi.core.architecture_contracts import UserRoleV2
from chatbi.files.contracts import FileShareRecord, UserUploadedFile


def new_share_id() -> str:
    return f"shr_{uuid4().hex}"


class FileAccessDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


_ORG_SCOPE_ROLES: frozenset[UserRoleV2] = frozenset({"analyst", "admin"})


class FileAccessChecker:
    """Evaluate the section 6.14 access matrix for one file and one requester."""

    def check(
        self,
        *,
        requester_user_id: str,
        requester_org_id: str,
        role: UserRoleV2,
        file: UserUploadedFile,
        shares: Sequence[FileShareRecord] = (),
    ) -> FileAccessDecision:
        # Spec FV10.3 §6.3: archived is a strict precondition, checked before
        # ownership/scope/share branches — an archived file's own owner must
        # NOT fall through to the file.user_id == requester_user_id ALLOW below.
        if file.archived_at is not None:
            if role == "admin" and file.org_id == requester_org_id:
                return FileAccessDecision.ALLOW
            return FileAccessDecision.DENY

        if file.user_id == requester_user_id:
            return FileAccessDecision.ALLOW

        if file.scope == "org" and file.org_id == requester_org_id and role in _ORG_SCOPE_ROLES:
            return FileAccessDecision.ALLOW

        if file.scope == "team" and self._has_active_share(requester_user_id, file.file_id, shares):
            return FileAccessDecision.ALLOW

        if role == "admin" and file.org_id == requester_org_id:
            return FileAccessDecision.ALLOW

        return FileAccessDecision.DENY

    def _has_active_share(
        self,
        requester_user_id: str,
        file_id: str,
        shares: Sequence[FileShareRecord],
    ) -> bool:
        return any(
            share.file_id == file_id and share.granted_to == requester_user_id and share.is_active
            for share in shares
        )
