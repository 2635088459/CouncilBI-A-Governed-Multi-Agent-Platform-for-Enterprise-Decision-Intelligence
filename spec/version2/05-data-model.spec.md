# Spec v2: Data Model

Source design:
- [Chinese design](../../system_design/05-data-model-design/VERSION2.zh-CN.md)
- [English design](../../system_design/05-data-model-design/VERSION2.en.md)

## 1. Purpose
Define the v2 persistent data foundation for business sample data, semantic catalog, runtime history, governance, evaluation, and knowledge retrieval.

## 2. Scope
In scope:
- PostgreSQL schemas: `business`, `semantic`, `runtime`, `governance`, `evaluation`, `knowledge`.
- Migration and seed reproducibility.
- Trace-based relationships across history, audit, trace, and evaluation records.
- Indexing and partitioning rules that can be tested.

Out of scope:
- Full enterprise warehouse modeling such as ODS/DWD/DWS.
- Production backup tooling implementation.
- Cross-region replication.

## 3. Typed Inputs and Outputs

### 3.1 MigrationResult
Required fields:
- `version: str`
- `applied_at: datetime`
- `status: Literal["succeeded", "failed"]`
- `error: str | null`

### 3.2 QueryHistoryRecord
Required fields:
- `trace_id: str`
- `session_id: str`
- `message_id: str`
- `status: Literal["succeeded", "failed", "degraded"]`
- `created_at: datetime`

### 3.3 TraceLinkedRecord
Required fields:
- `trace_id: str`
- `record_type: Literal["message", "query_result", "agent_trace", "audit_event", "eval_score"]`
- `record_id: str`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-05-001 | Empty database MUST be creatable from migrations without manual SQL. | Migration test |
| VR-05-002 | Seed data MUST include at least one KPI query fixture, one anomaly fixture, one RAG fixture, and one permission fixture. | Seed test |
| VR-05-003 | Runtime tables that store request state MUST include `trace_id`. | Schema test |
| VR-05-004 | Redis MUST NOT be the only storage for final answer, audit, or trace records. | Integration test |
| VR-05-005 | `query_results.trace_id` MUST be unique. | Schema constraint test |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-05-001 | Migration MUST create all six v2 schemas. |
| FR-05-002 | Migration MUST create `sessions`, `messages`, `query_results`, and `agent_traces`. |
| FR-05-003 | Migration MUST create `metrics`, `dimensions`, and `semantic_versions`. |
| FR-05-004 | Migration MUST create `documents`, `doc_chunks`, and embedding metadata. |
| FR-05-005 | Seed data MUST support one complete end-to-end demo query. |
| FR-05-006 | Records for one completed query MUST be joinable by `trace_id`. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-05-001 | Full migration on a blank local PostgreSQL database MUST complete in <= 30s. |
| NFR-05-002 | Fetching query history by `session_id` and `created_at` over 10,000 messages MUST complete P95 <= 200ms locally. |
| NFR-05-003 | Schema tests MUST verify required indexes and unique constraints exist. |
| NFR-05-004 | Pyright MUST report 0 errors for data access models and repository interfaces. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-05-001 | A blank database has schemas `business`, `semantic`, `runtime`, `governance`, `evaluation`, and `knowledge` after migration. |
| AC-05-002 | Seeded database contains metric `revenue`, at least one session, at least one document, and one restricted field policy. |
| AC-05-003 | Inserting duplicate `query_results.trace_id` fails. |
| AC-05-004 | One demo query can join message, query_result, agent_trace, and audit_event by trace id. |
| AC-05-005 | Query history lookup uses the expected index in explain plan or completes under threshold. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-05-001 | pyright | Validate repository and data models. |
| TC-05-002 | pytest migration | Apply migrations to blank database and assert schemas. |
| TC-05-003 | pytest seed | Assert required seed fixtures exist. |
| TC-05-004 | pytest constraint | Duplicate `query_results.trace_id` fails. |
| TC-05-005 | pytest integration | Join completed query records by trace id. |
| TC-05-006 | benchmark | Measure history lookup over 10,000 messages. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-05-001 | AC-05-001 | TC-05-002 |
| FR-05-002 | AC-05-004 | TC-05-005 |
| FR-05-003 | AC-05-002 | TC-05-003 |
| FR-05-004 | AC-05-002 | TC-05-003 |
| FR-05-005 | AC-05-002 | TC-05-003 |
| FR-05-006 | AC-05-004 | TC-05-005 |
| NFR-05-001 | AC-05-001 | TC-05-002 |
| NFR-05-002 | AC-05-005 | TC-05-006 |
| NFR-05-003 | AC-05-003 | TC-05-004 |
| NFR-05-004 | AC-05-001 | TC-05-001 |

## 10. First Red-Green Steps
1. Add migration metadata table only.
2. Add `runtime.sessions` and a schema test.
3. Add `runtime.query_results.trace_id` unique constraint.
4. Add one revenue seed metric.

