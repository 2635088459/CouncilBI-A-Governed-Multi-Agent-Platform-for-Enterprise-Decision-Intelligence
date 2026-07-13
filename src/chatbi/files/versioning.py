"""FileVersionManager: the FR-FV10-029 file_group_id version chain.

Re-uploading a file under the same ``(org_id, user_id, original_name)``
must create a new ``user_uploaded_files`` row with an incremented
``version_number`` and ``is_latest=TRUE``, while every older version in the
same ``file_group_id`` chain flips to ``is_latest=FALSE``. This module only
computes that assignment; persisting both the new record and the flipped
previous-latest record is the caller's job (the upload worker).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from chatbi.files.contracts import UserUploadedFile


def new_file_id() -> str:
    return f"ufile_{uuid4().hex}"


def new_file_group_id() -> str:
    return f"fgrp_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class VersionAssignment:
    """What the caller must persist to record one new upload version."""

    file_id: str
    file_group_id: str
    version_number: int
    superseded_previous_latest: UserUploadedFile | None = None


class FileVersionManager:
    """Assign version numbers and file_group_id chains for uploaded files."""

    def on_upload(
        self,
        file_group_id: str | None,
        previous_latest: UserUploadedFile | None = None,
    ) -> VersionAssignment:
        if file_group_id is None:
            return VersionAssignment(
                file_id=new_file_id(),
                file_group_id=new_file_group_id(),
                version_number=1,
                superseded_previous_latest=None,
            )

        if previous_latest is None:
            raise ValueError("previous_latest is required when file_group_id is provided")

        return VersionAssignment(
            file_id=new_file_id(),
            file_group_id=file_group_id,
            version_number=previous_latest.version_number + 1,
            superseded_previous_latest=replace(previous_latest, is_latest=False),
        )
