# Spec FV10.2: File Sharing Approval Workflow

Source design:
- [10.2 File Sharing Approval Workflow design](../../../system_design/final-version/en/10-followups/02-file-sharing-approval-workflow.en.md)
- [Spec FV10.1: RAG Per-User Isolation](01-rag-per-user-isolation.spec.en.md) (dependency: approval widens RAG visibility defined there)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; revises FR-FV10-026/027/033 admin-initiated promotion)

---

## 1. Purpose

Replace admin-initiated file promotion with an analyst-requested, admin-approved sharing flow, and define the sharing grain precisely as "same organization, same role as the requester" rather than "entire organization."

## 2. Scope

**In scope:**
- `FileShareRequest` record and its state machine (`pending` → `approved` | `rejected`).
- `POST /api/v2/files/{file_id}/share-requests`.
- `GET /api/v2/admin/share-requests`, `POST .../approve`, `POST .../reject`.
- Fan-out logic: resolving "every user in the requester's org with the requester's role."
- Widening `KnowledgeDocument` visibility (Spec FV10.1) as a side effect of approval, when the shared file is unstructured and already promoted.

**Out of scope:**
- Self-service promotion into a user's own private knowledge tier (unchanged, no approval required, already in scope of the parent FV-10 spec's promotion feature at the "private" tier).
- Any change to `FileShareRecord`'s own shape or to `FileAccessChecker`'s access-decision logic — both are reused unmodified.
- Notifying users out-of-band (email/Slack) of request status changes.

## 3. Actors

| Actor | New capability in this spec |
|---|---|
| Analyst / Business user (file owner) | May submit one pending share request per owned file. |
| Admin | Reviews and approves/rejects pending requests within their own org. |

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-041 | A file owner MAY submit `POST /api/v2/files/{file_id}/share-requests`. If a `pending` request already exists for that `file_id`, the system MUST return HTTP 409. |
| FR-FV10-042 | Approving a request MUST create one `FileShareRecord` for every user in the requester's `org_id` who holds the requester's role **at approval time**. Users granted that role after approval MUST NOT be retroactively added. |
| FR-FV10-043 | If the shared file is `file_type=unstructured` and has `promoted_to_doc_id IS NOT NULL`, approval MUST also widen that document's RAG visibility to the same fan-out set defined in FR-FV10-042 (per Spec FV10.1 §4's `shared_visibility()`). |
| FR-FV10-044 | Rejecting a request MUST create no `FileShareRecord`s, MUST NOT alter the file's existing visibility, and MUST set `status=rejected` with `decided_by` and `decided_at` recorded. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-013 | Approval fan-out MUST be transactional: either every matching user receives a `FileShareRecord` and the request is marked approved, or none do and the request remains `pending` (no partial fan-out on failure). |
| NFR-FV10-014 | A user submitting a share request for a file they do not own MUST receive HTTP 403/404 consistent with the parent spec's existence-disclosure rule (FR-FV10-036, NFR-FV10-005). |

## 6. Data Contracts

### 6.1 `FileShareRequest`

```python
@dataclass(frozen=True, slots=True)
class FileShareRequest:
    request_id: str          # prefix req_share_
    file_id: str
    requested_by: str        # user_id
    org_id: str
    role: str                # requester's role at request time; fan-out target
    status: Literal["pending", "approved", "rejected"]
    requested_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None
```

### 6.2 Endpoints

| Method | Path | Request body | Response |
|---|---|---|---|
| `POST` | `/api/v2/files/{file_id}/share-requests` | `{}` | `201` with the created `FileShareRequest`; `409` if a pending request already exists |
| `GET` | `/api/v2/admin/share-requests?status=pending` | — | List of `FileShareRequest`, scoped to the admin's `org_id` |
| `POST` | `/api/v2/admin/share-requests/{request_id}/approve` | `{}` | `200`; triggers fan-out per FR-FV10-042/043 |
| `POST` | `/api/v2/admin/share-requests/{request_id}/reject` | `{"reason": str \| None}` | `200` |

### 6.3 Required PostgreSQL Table

```
file_share_requests
```

Indexes required:
- `(file_id, status)` — to enforce the one-pending-request-per-file rule (FR-FV10-041)
- `(org_id, status, requested_at DESC)` — for the admin listing endpoint

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-034 | A file owner submits a share request; a second submission for the same file while the first is still pending returns HTTP 409. |
| AC-FV10-035 | After approval, every other analyst in the requester's org (and only analysts, if the requester is an analyst) can access the file via `GET /api/v2/files/{file_id}`; an admin in the same org who is not also an analyst cannot. |
| AC-FV10-036 | After approval of a request for an already-promoted unstructured file, a colleague covered by the fan-out set retrieves the file's RAG content in a matching chat query; a colleague NOT covered by the fan-out set does not. |
| AC-FV10-037 | After rejection, the file remains inaccessible to anyone other than the owner, and no `FileShareRecord` exists for this file beyond what existed before the request. |

## 8. Test Plan

### 8.1 Unit Tests — Request Lifecycle

| ID | Layer | Description |
|---|---|---|
| TC-FV10-116 | unit | Creating a share request for a file with no existing pending request succeeds and returns `status=pending`. |
| TC-FV10-117 | unit | Creating a second share request for a file that already has a `pending` request raises a conflict error. |
| TC-FV10-118 | unit | Creating a share request is allowed again once the prior request has been `approved` or `rejected` (not blocked by history, only by an active `pending` request). |

### 8.2 Unit Tests — Approval Fan-Out

| ID | Layer | Description |
|---|---|---|
| TC-FV10-119 | unit | Approving a request from an `analyst` in `org_acme` creates a `FileShareRecord` for every other `analyst` user in `org_acme`, and none for `admin` or `business_user` accounts in that org. |
| TC-FV10-120 | unit | Approving a request creates no `FileShareRecord`s for users in a different `org_id`, even if they share the requester's role. |
| TC-FV10-121 | unit | Approving a request for a structured (not unstructured) file creates `FileShareRecord`s but does not attempt any RAG-visibility widening call. |
| TC-FV10-122 | unit | Approving a request for a promoted unstructured file widens the corresponding `KnowledgeDocument`'s visibility to the same user set as the `FileShareRecord` fan-out. |
| TC-FV10-123 | unit | Rejecting a pending request creates zero `FileShareRecord`s and sets `status=rejected`, `decided_by`, `decided_at`. |

### 8.3 Integration Tests — HTTP Flow

| ID | Layer | Description |
|---|---|---|
| TC-FV10-124 | integration | Full flow via HTTP: analyst uploads and promotes a PDF, requests sharing, admin approves, a same-role colleague's chat query (no `file_ids`) surfaces the file's promoted evidence; an admin account in the same org does not see it. |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-041 | AC-FV10-034 | TC-FV10-116, TC-FV10-117, TC-FV10-118 |
| FR-FV10-042 | AC-FV10-035 | TC-FV10-119, TC-FV10-120, TC-FV10-124 |
| FR-FV10-043 | AC-FV10-036 | TC-FV10-121, TC-FV10-122, TC-FV10-124 |
| FR-FV10-044 | AC-FV10-037 | TC-FV10-123 |
| NFR-FV10-013 | AC-FV10-035 | TC-FV10-119 |
| NFR-FV10-014 | AC-FV10-034 | TC-FV10-116 |

## 10. Implementation Notes

- The fan-out query ("every user in `org_id` with role `X`") reuses the existing `AuthStore`; no new user-listing capability needs to be built beyond what `admin_update_roles_v2` and similar admin endpoints already imply exists.
- This spec deliberately does not define a "who can see share requests they submitted" listing endpoint for the requester — out of scope for this pass; the requester currently has no way to check their own request's status other than noticing the file became shared. Flagged here as a likely fast follow, not silently decided.
