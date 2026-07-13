# Spec FV10.3: File Retention, Auto-Archival, and Re-Upload Dedup

Source design:
- [10.3 File Retention, Auto-Archival, and Re-Upload Dedup design](../../../system_design/final-version/en/10-followups/03-file-retention-and-archival.en.md)
- [Spec FV10.1: RAG Per-User Isolation](01-rag-per-user-isolation.spec.en.md) (dependency: archival deactivates promoted RAG content)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; supersedes FR-FV10-032's destructive retention worker)

---

## 1. Purpose

Replace the destructive, never-scheduled `RetentionWorker` with an archival model: shorter retention windows (10 days for `user` scope, 60 for `team` scope), archival that preserves bytes and metadata but revokes access for everyone except `admin`, content-hash-based deduplication on re-upload, and an actual daily schedule.

## 2. Scope

**In scope:**
- Shortening `RETENTION_THRESHOLDS` for `user` and `team` scope.
- A new `archived_at` field and archival semantics distinct from `deleted_at`.
- `FileAccessChecker` precondition: archived files are admin-only regardless of ownership/share grants.
- A new `content_hash` field, computed at upload, used to detect and purge duplicate archived content on re-upload.
- Deactivating a file's promoted RAG content at the moment of archival (Spec FV10.1).
- An admin-only archived-files listing/export endpoint.
- Actually scheduling `RetentionWorker.run()` to execute at least daily.

**Out of scope:**
- Any pipeline that loads archived content into the governed business database — explicitly a different team's responsibility; this spec only makes the archive inspectable/exportable.
- Changing `session`-scope retention (unchanged at 24 hours) or `org`-scope behavior (unchanged: not swept).
- A distributed job queue; the scheduling mechanism in this spec is a single periodic in-process task, not a new piece of infrastructure.

## 3. Actors

| Actor | Behavior change in this spec |
|---|---|
| Business user / Analyst (file owner) | Loses access to their own file once it archives; must re-upload to regain a usable copy. |
| Admin | Gains the ability to view/export archived files org-wide; this is the only role with archived-file access. |
| Background worker | `RetentionWorker` now archives instead of purging, and actually runs on a schedule. |

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-045 | `RetentionWorker` MUST archive (not purge) `user`-scope files 10 days after `last_accessed_at` (or `created_at` if never accessed), and `team`-scope files 60 days after the same reference point. |
| FR-FV10-046 | Archiving MUST preserve the file's object-storage bytes (original and any Parquet snapshot) and its Postgres metadata row. Neither may be deleted at archival time. |
| FR-FV10-047 | `FileAccessChecker.check()` MUST deny access to a file where `archived_at IS NOT NULL` for every requester except one with `role == "admin"` in the file's `org_id`, regardless of ownership or any active `FileShareRecord`. |
| FR-FV10-048 | Archiving a file with `promoted_to_doc_id IS NOT NULL` MUST remove the corresponding `KnowledgeDocument` and its chunks from both the live knowledge store and Postgres (reusing `KnowledgePromotionService.demote_document()`'s removal logic), and MUST clear `promoted_to_doc_id` on the file record. |
| FR-FV10-049 | On a new upload, the system MUST compute a `content_hash` (SHA-256 of the raw bytes) and, if it matches an archived file owned by the same `user_id`, MUST purge that archived file's object-storage bytes and hard-delete its metadata row before proceeding with the new upload. |
| FR-FV10-050 | `RetentionWorker.run()` MUST execute at least once every 24 hours in the running deployment via an actual scheduling mechanism (not merely exist as unwired code). |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-015 | Archival MUST be idempotent: running the retention sweep twice against the same already-archived file must not error and must not double-process it (e.g. must not attempt to demote an already-demoted RAG document). |
| NFR-FV10-016 | Content-hash computation MUST NOT block the upload response beyond the existing upload-latency budget defined in NFR-FV10-001 of the parent spec. |
| NFR-FV10-017 | Dedup matching MUST be scoped strictly to `content_hash` equality **and** same `user_id`; it MUST NOT match across different users even with byte-identical content. |

## 6. Data Contracts

### 6.1 `UserUploadedFile` (extended)

```python
@dataclass(frozen=True, slots=True)
class UserUploadedFile:
    # ... existing fields unchanged ...
    content_hash: str                      # NEW — SHA-256 hex digest of raw uploaded bytes
    archived_at: datetime | None = None    # NEW — distinct from deleted_at
```

### 6.2 Updated Retention Thresholds

```python
RETENTION_THRESHOLDS: dict[FileScope, timedelta] = {
    "session": timedelta(hours=24),   # unchanged
    "user": timedelta(days=10),        # was 30
    "team": timedelta(days=60),        # was 90
}
```

### 6.3 Access Permission Matrix (supersedes parent spec §6.14)

| Condition | Result |
|---|---|
| `file.archived_at IS NOT NULL AND role != 'admin'` | DENY, regardless of any other condition below |
| `file.archived_at IS NOT NULL AND role == 'admin' AND file.org_id == current_org_id` | ALLOW |
| `file.user_id == current_user_id` (and not archived) | ALLOW |
| `file.scope == 'org' AND file.org_id == current_org_id AND role IN ('analyst','admin')` (and not archived) | ALLOW |
| `file.scope == 'team' AND active share exists for current_user_id` (and not archived) | ALLOW |
| `current_role == 'admin' AND file.org_id == current_org_id` (and not archived) | ALLOW |
| Any other case | DENY → HTTP 404 (no existence disclosure, per parent spec FR-FV10-036) |

### 6.4 Endpoint

`GET /api/v2/admin/files/archived` (or `status=archived` filter on the existing `GET /api/v2/admin/files`) — admin-only, returns archived files org-wide with a signed download URL for each, reusing the existing presigned-download mechanism.

### 6.5 Postgres Migration

```sql
ALTER TABLE user_uploaded_files ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE user_uploaded_files ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_content_hash ON user_uploaded_files(user_id, content_hash) WHERE archived_at IS NOT NULL;
```

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-038 | A `user`-scope file untouched for 10 days is archived: `archived_at` is set, object-storage bytes still exist, and the owner's `GET /api/v2/files/{file_id}` now returns HTTP 404. |
| AC-FV10-039 | A `team`-scope file untouched for 60 days is archived under the same conditions as AC-FV10-038, and every user who previously held a `FileShareRecord` for it also loses access. |
| AC-FV10-040 | An admin in the file's org can retrieve and download an archived file via the admin-only endpoint; a non-admin (including the original owner) cannot, even via that same endpoint. |
| AC-FV10-041 | Archiving a promoted file removes its evidence from a subsequent matching RAG query from any user who previously could see it, and `promoted_to_doc_id` reads `None` on the archived file record. |
| AC-FV10-042 | Re-uploading byte-identical content to a file that is currently archived (same uploader) results in exactly one active file record (the new upload) and zero archived records for that content; storage usage reflects only the new copy. |
| AC-FV10-043 | Re-uploading byte-identical content as a *different* user than the one who owns the archived copy does not purge the other user's archived file; both an archived record (untouched) and a new active record exist afterward. |

## 8. Test Plan

### 8.1 Unit Tests — Archival Semantics

| ID | Layer | Description |
|---|---|---|
| TC-FV10-125 | unit | `RetentionWorker.run()` sets `archived_at` (not `deleted_at`) on a `user`-scope file whose `last_accessed_at` is 10 days in the past, and leaves the file's bytes in the fake object-storage adapter untouched. |
| TC-FV10-126 | unit | `RetentionWorker.run()` does not archive a `user`-scope file whose `last_accessed_at` is 9 days in the past. |
| TC-FV10-127 | unit | `RetentionWorker.run()` archives a `team`-scope file at the 60-day threshold, not the old 90-day one. |
| TC-FV10-128 | unit | Running `RetentionWorker.run()` twice against an already-archived file is a no-op the second time (idempotency, NFR-FV10-015). |

### 8.2 Unit Tests — Access Control

| ID | Layer | Description |
|---|---|---|
| TC-FV10-129 | unit | `FileAccessChecker.check()` denies the file's own owner once `archived_at` is set, even though `file.user_id == requester_user_id`. |
| TC-FV10-130 | unit | `FileAccessChecker.check()` denies a user holding an active `FileShareRecord` once the file is archived. |
| TC-FV10-131 | unit | `FileAccessChecker.check()` allows `role == "admin"` in the same `org_id` for an archived file. |

### 8.3 Unit Tests — RAG Deactivation on Archival

| ID | Layer | Description |
|---|---|---|
| TC-FV10-132 | unit | Archiving a file with `promoted_to_doc_id` set removes the corresponding `KnowledgeDocument` from `InMemoryKnowledgeStore` and clears `promoted_to_doc_id` on the archived record. |

### 8.4 Unit Tests — Dedup on Re-Upload

| ID | Layer | Description |
|---|---|---|
| TC-FV10-133 | unit | Uploading content whose hash matches an archived file owned by the same user purges that archived file's bytes and metadata row. |
| TC-FV10-134 | unit | Uploading content whose hash matches an archived file owned by a **different** user does not purge anything; the archived file is untouched. |
| TC-FV10-135 | unit | Uploading genuinely new content (no hash match) never triggers any purge. |

### 8.5 Integration Tests — Scheduling

| ID | Layer | Description |
|---|---|---|
| TC-FV10-136 | integration | The application, once started, invokes `RetentionWorker.run()` at least once within a bounded test window (verifies the scheduling loop actually fires, using a short interval override for the test rather than waiting 24 hours). |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-045 | AC-FV10-038, AC-FV10-039 | TC-FV10-125, TC-FV10-126, TC-FV10-127 |
| FR-FV10-046 | AC-FV10-038 | TC-FV10-125 |
| FR-FV10-047 | AC-FV10-038, AC-FV10-039, AC-FV10-040 | TC-FV10-129, TC-FV10-130, TC-FV10-131 |
| FR-FV10-048 | AC-FV10-041 | TC-FV10-132 |
| FR-FV10-049 | AC-FV10-042, AC-FV10-043 | TC-FV10-133, TC-FV10-134, TC-FV10-135 |
| FR-FV10-050 | — | TC-FV10-136 |
| NFR-FV10-015 | — | TC-FV10-128 |
| NFR-FV10-016 | — | (covered by parent spec's NFR-FV10-001 upload-latency suite, re-run with hashing enabled) |
| NFR-FV10-017 | AC-FV10-043 | TC-FV10-134 |

## 10. Implementation Notes

- §6.3's access matrix is a strict supersede of the parent spec's §6.14 — the archived-file precondition MUST be checked first, before any of the existing ownership/scope branches, since an archived file's owner would otherwise incorrectly pass the `file.user_id == current_user_id` branch.
- The admin-only archived-files endpoint (§6.4) intentionally has no delete/restore action in this spec — restoring from archive is not a defined workflow; the only path back to a usable file is re-upload (FR-FV10-049's context).
