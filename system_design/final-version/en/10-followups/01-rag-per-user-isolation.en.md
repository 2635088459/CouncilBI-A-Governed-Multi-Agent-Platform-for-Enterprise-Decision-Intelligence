# 10.1 RAG Per-User Isolation

## 1. Problem Solved

The knowledge base RAG agent (`RagAgentRunner` → `InMemoryKnowledgeStore`) currently has **no tenant or user boundary at all**. `KnowledgeDocument` has no `org_id` and no `owner_user_id`; `RetrievalQuery` carries no identity; `_load_knowledge_store_from_db` loads every row from `knowledge.documents` with no `WHERE` clause. The practical effect: a document promoted by an analyst in one organization, or a seeded company document, is retrievable by **any user in any organization** who asks a matching question.

This directly contradicts the platform's governed multi-tenant premise (`org_acme`, `org_techstart`, `org_globalretail` are supposed to be isolated) and, on top of that, the user-uploaded portion of the knowledge base needs to be private **per person**, not just per tenant: an analyst's own promoted files should not be visible to a colleague in the same org unless explicitly shared (see [10.2 File Sharing Approval Workflow](02-file-sharing-approval-workflow.en.md)).

## 2. Two Knowledge Tiers

The fix is not "make everything private." There are two categories of content in the knowledge base today, and they need different rules:

| Tier | Examples | Owner | Visibility |
|---|---|---|---|
| **Baseline / system knowledge** | The 15 seeded company documents (revenue policy, quarterly business reviews, metric definitions, governance policy manual) | Nobody — these are platform content, not user uploads | Unchanged: gated by `allowed_roles` as today (e.g. `analyst`, `admin`), visible to everyone in that role across the platform |
| **User-uploaded personal knowledge** | A file an analyst uploads and promotes for their own use | The uploading user | **Private by default.** Visible only to the owner, unless explicitly shared (see 10.2) |

Baseline documents are **not archived or expired** by this change or by [10.3 File Retention and Archival](03-file-retention-and-archival.en.md) — they are permanent platform content, not subject to any user's file lifecycle.

## 3. Data Model Changes

`KnowledgeDocument` (`src/chatbi/knowledge.py`) gains one new field:

```python
@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    source_id: str
    title: str
    doc_type: str
    publish_time: datetime
    tags: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ()
    owner_user_id: str | None = None   # NEW. None = baseline/system document.
```

Postgres `knowledge.documents` gains a nullable `owner_user_id TEXT` column (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, matching the existing migration style in this codebase). Existing seeded rows keep `owner_user_id = NULL`.

`RetrievalQuery` gains the identity of the asker:

```python
@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    question: str
    requesting_user_id: str            # NEW, required
    ...  # existing fields unchanged
```

## 4. Retrieval Filtering

`InMemoryKnowledgeStore.list_chunk_records` (and therefore `retrieve()`) adds one more filter, applied alongside the existing `doc_type`/`published_from`/`published_to`/`user_role`/`tags` checks:

```
a document is eligible for this query if:
    document.owner_user_id is None                       # baseline knowledge: always eligible (subject to allowed_roles as today)
    OR document.owner_user_id == requesting_user_id       # the asker's own promoted content
    OR requesting_user_id in shared_visibility(document)  # granted via 10.2's approval workflow
```

`shared_visibility(document)` is not a new field on `KnowledgeDocument` itself — it is derived the same way file access already works: a widened-visibility document is one whose *source file* has active `FileShareRecord` grants for the requesting user (see 10.2 for exactly how a share grant gets created). The knowledge store does not need to know about files at all; the HTTP layer resolves "does this user have a share grant for the file this document was promoted from" before calling `retrieve()`, and passes the resulting set of visible `owner_user_id`s (or just widens `requesting_user_id` matching to include shared documents — implementation detail to settle when this is built, not a design fork).

## 5. Who Populates `owner_user_id`

- **Seeded/baseline documents**: unchanged, `owner_user_id` stays `NULL` forever. `scripts/seed_demo_data.sql` does not set it.
- **User-promoted documents**: `KnowledgePromotionService.promote_file()` (`src/chatbi/files/promotion.py`) sets `owner_user_id=file.user_id` when it builds the `KnowledgeDocument` it writes into the live knowledge store and into Postgres. This is a one-line change to the `_index_into_live_rag` helper already built for [FV-10's promotion wiring](../10-user-file-upload-and-hybrid-analysis.en.md).

## 6. What This Does *Not* Change

- Promotion still requires admin approval for anything beyond "visible only to me" (10.1 is about *filtering*, not about *who is allowed to promote* — an analyst promoting into their own private tier needs no approval per [10.2](02-file-sharing-approval-workflow.en.md)'s decision).
- The federated-query business-table catalog (`business_table_catalog.py`) is untouched — that already reads live Postgres `business.*` + `governance.access_policies`, a completely separate mechanism from the knowledge base.
- `SqlObjectAccessPolicy`/`DataModelCatalog` (`chatbi/data_model.py`) are untouched — they were already established as describing an aspirational schema, not the live one, and have no relationship to RAG.

## 7. Requirement IDs

| ID | Requirement |
|---|---|
| FR-FV10-037 | `KnowledgeDocument`/Postgres `knowledge.documents` must carry an `owner_user_id` that is `NULL` for baseline/system documents. |
| FR-FV10-038 | Baseline documents (`owner_user_id IS NULL`) remain visible per existing `allowed_roles` rules, unaffected by this change. |
| FR-FV10-039 | A document with `owner_user_id` set is retrievable only by that user, or by a user holding an active share grant for the source file (see FR-FV10-041+). |
| FR-FV10-040 | `KnowledgePromotionService.promote_file()` must stamp `owner_user_id` with the uploading user's `user_id` when a user file is promoted. |
