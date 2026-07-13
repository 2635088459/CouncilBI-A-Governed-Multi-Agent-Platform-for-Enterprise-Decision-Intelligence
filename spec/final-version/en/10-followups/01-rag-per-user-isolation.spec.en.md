# Spec FV10.1: RAG Per-User Isolation

Source design:
- [10.1 RAG Per-User Isolation design](../../../system_design/final-version/en/10-followups/01-rag-per-user-isolation.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; FR-FV10-023, FR-FV10-033/034 are the promotion requirements this spec revises)

---

## 1. Purpose

Close a confirmed cross-tenant data leak in the RAG knowledge base: `KnowledgeDocument` and `RetrievalQuery` currently carry no identity, so any user in any organization can retrieve any promoted or seeded document. Define the corrected contract: baseline/system knowledge stays role-gated and universally visible as today; user-promoted knowledge becomes private to the promoting user by default, widened only through [Spec FV10.2](02-file-sharing-approval-workflow.spec.en.md)'s approval flow.

## 2. Scope

**In scope:**
- Adding `owner_user_id` to `KnowledgeDocument` and the Postgres `knowledge.documents` table.
- Adding `requesting_user_id` to `RetrievalQuery` and enforcing it in `InMemoryKnowledgeStore.retrieve()`.
- Updating `KnowledgePromotionService.promote_file()` to stamp ownership.
- Verifying baseline/seeded documents are unaffected.

**Out of scope:**
- The share-grant mechanism that widens visibility beyond the owner (see Spec FV10.2).
- Any change to `business_table_catalog.py` or `SqlObjectAccessPolicy` (unrelated systems, confirmed in the source design).
- Vector similarity scoring changes (this spec is about *which documents are eligible*, not how eligible documents are ranked).

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3 (`business_user`, `analyst`, `admin`). No new actor is introduced; every actor's own promoted content is private to them by this spec.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-037 | `KnowledgeDocument` and the Postgres `knowledge.documents` table MUST carry a nullable `owner_user_id`. Seeded/baseline documents MUST have `owner_user_id = NULL`. |
| FR-FV10-038 | A document with `owner_user_id IS NULL` MUST remain retrievable per the existing `allowed_roles` rule, unaffected by `requesting_user_id`. |
| FR-FV10-039 | A document with `owner_user_id` set MUST be excluded from `retrieve()` results unless `requesting_user_id == owner_user_id`, or the requester holds an active share grant for the document's source file (Spec FV10.2). |
| FR-FV10-040 | `KnowledgePromotionService.promote_file()` MUST set `owner_user_id` to the uploading user's `user_id` on both the live `InMemoryKnowledgeStore` write and the Postgres `knowledge.documents` write. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-011 | Cross-user leakage MUST be zero under concurrent load: User A's retrieval MUST NEVER include a document owned by User B, tested with concurrent requests from both users against a shared store instance. |
| NFR-FV10-012 | Adding the ownership filter MUST NOT change retrieval latency or ranking order for baseline documents (`owner_user_id IS NULL`) relative to pre-change behavior. |

## 6. Data Contracts

### 6.1 `KnowledgeDocument` (extended)

```python
@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    source_id: str
    title: str
    doc_type: str
    publish_time: datetime
    tags: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ()
    owner_user_id: str | None = None   # NEW
```

### 6.2 `RetrievalQuery` (extended)

```python
@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    question: str
    requesting_user_id: str            # NEW, required
    metric_context: str = ""
    doc_type: str | None = None
    doc_types: tuple[str, ...] = ()
    published_from: datetime | None = None
    published_to: datetime | None = None
    user_role: str | None = None
    tags: tuple[str, ...] = ()
    top_k: int = 5
    query_embedding: tuple[float, ...] | None = None
```

### 6.3 Postgres Migration

```sql
ALTER TABLE knowledge.documents ADD COLUMN IF NOT EXISTS owner_user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_owner ON knowledge.documents(owner_user_id) WHERE owner_user_id IS NOT NULL;
```

`_load_knowledge_store_from_db` MUST select `owner_user_id` alongside the existing columns and pass it into `KnowledgeDocument`.

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-030 | User A promotes a file into their own knowledge tier; User A's subsequent matching question retrieves that document. |
| AC-FV10-031 | User B (different user, same org) asks the same matching question as User A in AC-FV10-030; User B's result does NOT include User A's document. |
| AC-FV10-032 | A seeded baseline document (`owner_user_id = NULL`) remains retrievable by any user whose role is in the document's `allowed_roles`, regardless of who is asking. |
| AC-FV10-033 | A restart of the process (which reloads `InMemoryKnowledgeStore` from Postgres via `_load_knowledge_store_from_db`) preserves `owner_user_id` on every previously promoted document. |

## 8. Test Plan

### 8.1 Unit Tests — `InMemoryKnowledgeStore` Filtering

| ID | Layer | Description |
|---|---|---|
| TC-FV10-107 | unit | `retrieve()` with `requesting_user_id=U1` returns a document where `owner_user_id=U1`. |
| TC-FV10-108 | unit | `retrieve()` with `requesting_user_id=U2` does NOT return a document where `owner_user_id=U1`, even when the question text matches closely. |
| TC-FV10-109 | unit | `retrieve()` with any `requesting_user_id` returns a document where `owner_user_id IS NULL`, subject to the existing `allowed_roles` check. |
| TC-FV10-110 | unit | `save_document()` accepts a `KnowledgeDocument` with `owner_user_id=None` (baseline) and one with `owner_user_id` set (user-owned) without validation error. |
| TC-FV10-111 | unit | A document owned by `U1` becomes retrievable by `U2` once a share-derived visibility check (mocked) reports `U2` as authorized (integration point for Spec FV10.2; this test stubs the share lookup). |

### 8.2 Unit Tests — Promotion Ownership Stamping

| ID | Layer | Description |
|---|---|---|
| TC-FV10-112 | unit | `KnowledgePromotionService.promote_file()` writes a `KnowledgeDocument` to the live knowledge store with `owner_user_id` equal to the source file's `user_id`. |
| TC-FV10-113 | unit | `KnowledgePromotionService.promote_file()` persists `owner_user_id` into the Postgres `knowledge.documents` row (live-Postgres test, guarded by `DATABASE_URL`, matching this codebase's existing live-DB test convention). |

### 8.3 Integration Tests — Cross-User Isolation via HTTP

| ID | Layer | Description |
|---|---|---|
| TC-FV10-114 | integration | Analyst A promotes an unstructured file; a `/api/v2/chat/query` from Analyst A (no `file_ids`, RAG-triggering question) surfaces the promoted document in `evidence_list`. |
| TC-FV10-115 | integration | The same question, asked by Analyst B in the same org, does NOT surface Analyst A's promoted document in `evidence_list`; seeded baseline evidence is unaffected for both. |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-037 | AC-FV10-030, AC-FV10-033 | TC-FV10-110, TC-FV10-113 |
| FR-FV10-038 | AC-FV10-032 | TC-FV10-109, TC-FV10-115 |
| FR-FV10-039 | AC-FV10-031, AC-FV10-032 | TC-FV10-107, TC-FV10-108, TC-FV10-111, TC-FV10-114, TC-FV10-115 |
| FR-FV10-040 | AC-FV10-030 | TC-FV10-112, TC-FV10-113 |
| NFR-FV10-011 | AC-FV10-031 | TC-FV10-108, TC-FV10-115 |
| NFR-FV10-012 | AC-FV10-032 | TC-FV10-109 |

## 10. Implementation Notes

- `KnowledgePromotionService` needs no new constructor parameter to satisfy this spec — `owner_user_id` is derived from the `UserUploadedFile.user_id` already passed into `promote_file()`.
- §6.1's `shared_visibility()` resolution (TC-FV10-111, TC-FV10-114) depends on Spec FV10.2's `FileShareRecord` fan-out; until that spec is implemented, `shared_visibility()` MAY be stubbed to always return an empty set without violating this spec's acceptance criteria.
