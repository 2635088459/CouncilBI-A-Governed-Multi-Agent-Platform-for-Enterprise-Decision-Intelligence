# 4.7 Durable Observability Storage for Golden Dataset Mining

## 1. Problem Solved

[4.6](06-real-golden-dataset-and-embedding-reload-fix.en.md) added `golden_dataset_mining.py`: a mechanism that scans real chat-query questions (`ObservabilityLogRecord`) cross-referenced against `rag_retrieved` trace spans with nonzero evidence (`ObservabilitySpan`), to surface a human-reviewable shortlist of real questions for growing `golden_dataset/cases.json` beyond its initial 24 hand-verified cases. That mechanism had a named, explicit limitation: `InMemoryObservabilityLogStore` and `InMemoryObservabilityStore` (`observability_logs.py`/`observability.py`) are process-local dictionaries with no durability — every log record and trace span is lost on restart, so mining could only ever see questions asked during the current process's uptime, never a deployment's actual history. This document closes that gap: a Postgres-backed implementation of both stores, wired in behind the same opt-in-flag convention this project already uses for [4.3](03-cross-encoder-reranking.en.md)'s reranker and [4.5](05-pgvector-production-vector-search.en.md)'s pgvector search.

## 2. What Already Exists

- `ObservabilityLogger.record()` (`observability_logs.py`) and `TraceRecorder.record()`/`.run_span()` (`observability.py`) already write every log record and trace span through a single storage boundary (`self._store`), which was, until now, always a concrete in-memory class — the natural seam for a swappable backend already existed, it just had only one implementation.
- Every chat request already writes several trace spans (`REQUEST_RECEIVED`, `SQL_GUARDRAIL_CHECKED`, `RAG_RETRIEVED` when evidence exists, `RESPONSE_SENT`, ...) plus at least one log record carrying the raw (PII-masked) question text — `application/app.py`'s `handle_chat_query()` is the call site golden dataset mining ultimately depends on.
- This project's existing Postgres-backed repositories (`PostgresAnalyticsRepository`, `PostgresKnowledgeVectorSource`, `PostgresAuthStore`, `PostgresRagRepository`) already establish an opt-in `RuntimeConfig` flag, off by default, gating whether `_build_default_chatbi_application()` (`api/http.py`) constructs the Postgres variant at all — this design reuses that convention directly. All of them also use a `connect_fn(database_url)` + per-call cursor pattern with no connection pooling; this design deliberately does not, for the reason §3.3 explains.
- `migrations.py`'s `V2_SCHEMA_NAMES`/`V2_SCHEMAS_SQL` already establish one schema per concern (`business`, `semantic`, `runtime`, `governance`, `evaluation`, `knowledge`, `rag`, `analytics`, `auth`) — a new `observability` schema follows that exact pattern rather than overloading an existing one.

## 3. Design

### 3.1 `ObservabilityLogStore`/`ObservabilityStore` protocols

`ObservabilityLogger`/`TraceRecorder` previously type-hinted their `store` constructor parameter and property as the concrete `InMemoryObservabilityLogStore`/`InMemoryObservabilityStore` classes. Both gain a `Protocol` in their own module instead:

```python
class ObservabilityLogStore(Protocol):
    def add(self, record: ObservabilityLogRecord) -> None: ...
    def list_by_trace_id(self, trace_id: str) -> tuple[ObservabilityLogRecord, ...]: ...
    def list_all(self) -> tuple[ObservabilityLogRecord, ...]: ...


class ObservabilityStore(Protocol):
    def add_span(self, span: ObservabilitySpan) -> None: ...
    def list_spans(self, trace_id: str) -> tuple[ObservabilitySpan, ...]: ...
    def replay(self, trace_id: str) -> TraceReplay | None: ...
    def list_all(self) -> tuple[ObservabilitySpan, ...]: ...
```

`replay()` is part of `ObservabilityStore` (not just a convenience method on the in-memory class) because `application/app.py`'s `handle_observability_trace_detail()` calls `self._trace_recorder.store.replay(trace_id)` directly — any backend substituted in must support it. `ChatBIApplication`'s own `observability_store`/`observability_log_store` properties, and `golden_dataset_mining.py`'s `mine_retrieval_labeling_candidates()` parameters, are retyped from the concrete classes to these protocols, so all three (the in-memory default, the new Postgres implementation, and any future backend) are interchangeable without touching call sites.

### 3.2 Schema migration

A new `observability` schema, added to `V2_SCHEMA_NAMES` and to `BASE_MIGRATION_SQL_STATEMENTS` (no risky extension like `CREATE EXTENSION vector` is involved, unlike [4.5](05-pgvector-production-vector-search.en.md)'s pgvector migration, so this can safely be part of the base migration rather than a separate opt-in one):

```sql
CREATE SCHEMA IF NOT EXISTS observability;
CREATE TABLE IF NOT EXISTS observability.log_records (
    log_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    user_id TEXT NOT NULL,
    service TEXT NOT NULL,
    event TEXT NOT NULL,
    request_id TEXT,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observability_log_records_trace_id
    ON observability.log_records(trace_id);
CREATE TABLE IF NOT EXISTS observability.trace_spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    span_name TEXT NOT NULL,
    status TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    duration_ms INTEGER CHECK (duration_ms >= 0),
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_observability_trace_spans_trace_id
    ON observability.trace_spans(trace_id);
```

Both tables need a synthetic primary key (`log_id`/`span_id`) since neither `ObservabilityLogRecord` nor `ObservabilitySpan` carries one — `PostgresObservabilityLogStore`/`PostgresObservabilityStore` generate one (`f"log_{uuid4().hex}"`/`f"span_{uuid4().hex}"`) at write time, never persisted back onto the in-memory dataclass. `attributes` uses `JSONB`, unlike [4.5](05-pgvector-production-vector-search.en.md)'s `vector` column — Postgres's JSON/JSONB types are natively supported by psycopg (no missing-type-adapter problem the way `vector` has), so reads come back as plain Python dicts with no manual parsing step, and writes only need an explicit `::jsonb` cast on a `json.dumps()`-serialized string (the same style [4.6](06-real-golden-dataset-and-embedding-reload-fix.en.md)'s seed SQL already uses for `doc_chunks.metadata`), not a bespoke text-format parser the way [4.5](05-pgvector-production-vector-search.en.md)'s `parse_pgvector_embedding()` needed.

### 3.3 `PostgresObservabilityLogStore` / `PostgresObservabilityStore`

New module `observability_postgres.py`, implementing the two protocols against the schema above. Unlike this project's other Postgres-backed stores, these two do **not** open and close a fresh connection per call — deliberately, not by inconsistency. A single chat request writes 3–5 log records/trace spans through these two stores alone, far more than the once-per-request calls `PostgresKnowledgeVectorSource`/`PostgresAnalyticsRepository` make; a fresh-connection-per-call pattern here would multiply connection churn accordingly under sustained traffic. Both classes instead accept a `ConnectionSource` (a small `Protocol` requiring only `.connection() -> AbstractContextManager[Any]`) and borrow — never own — a connection from it per call:

```python
class ConnectionSource(Protocol):
    def connection(self) -> AbstractContextManager[Any]: ...


class PostgresObservabilityLogStore:
    def __init__(self, pool: ConnectionSource) -> None:
        self._pool = pool

    def add(self, record: ObservabilityLogRecord) -> None:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(...)
```

`psycopg_pool.ConnectionPool` satisfies `ConnectionSource` directly — its own `.connection()` context manager already commits on success/rolls back on error and returns the connection to the pool on exit, so neither store method calls `.commit()` or `.close()` itself (doing so would be redundant at best, and closing a pooled connection would defeat pooling entirely). Tests use a small `FakePool` implementing the same protocol, so no real Postgres instance — or real `ConnectionPool`, whose background reconnect threads would be unwanted noise in a unit test — is needed to verify the SQL/parameters each method produces.

### 3.4 Wiring: an opt-in flag, not a default-on change

`RuntimeConfig` gains `observability_postgres_enabled: bool = False`, read from `CHATBI_OBSERVABILITY_POSTGRES_ENABLED`, following [4.3](03-cross-encoder-reranking.en.md)/[4.5](05-pgvector-production-vector-search.en.md)'s exact opt-in convention. `_build_default_chatbi_application()` (`api/http.py`) constructs exactly **one** `psycopg_pool.ConnectionPool` and hands it to both `PostgresObservabilityStore` and `PostgresObservabilityLogStore` — sharing one pool between them, since both write to the same database, rather than each maintaining its own separate set of connections — only when the flag is set **and** `database_url` is configured. Enabling the flag with no `database_url` is a no-op that falls back to the in-memory defaults, the same "needs a real Postgres instance" guard [4.5](05-pgvector-production-vector-search.en.md) applies to its own flag. `ChatBIApplication`'s constructor already accepted injectable `trace_recorder`/`observability_logger` parameters before this phase — no change was needed there, only at the one place that decides what to inject.

### 3.5 Pool shutdown

`ChatBIApplication` gains a small, generic `closeable_resources: tuple[Callable[[], None], ...] = ()` constructor parameter and a `close()` method that calls each one — not specific to connection pools, just a hook for any resource this application was handed but does not otherwise own the lifecycle of. `_build_default_chatbi_application()` registers `observability_connection_pool.close` when a pool was constructed. `create_app()`'s existing `_retention_sweep_lifespan` (added for [10.3](../10-followups/03-file-retention-and-archival.en.md)'s file-retention sweep) now also calls `chatbi_application.close()` in its shutdown path — composed into that one lifespan rather than adding a second, since FastAPI keeps only one `lifespan_context` per router.

### 3.6 Retention sweep

`ObservabilityLogStore`/`ObservabilityStore` gain a `prune_older_than(cutoff_at: datetime) -> int` method (implemented on all four classes — both in-memory and both Postgres-backed, so pruning is not a Postgres-only capability). `RuntimeConfig` gains `observability_retention_days: int = 30` (`CHATBI_OBSERVABILITY_RETENTION_DAYS`). A new `_run_observability_retention_sweep_loop()` (`api/http.py`) runs on the same schedule as [10.3](../10-followups/03-file-retention-and-archival.en.md)'s file-retention sweep — a single in-process `asyncio` loop, not a distributed job queue, for the same reason that sweep already is one — and is started as a second task inside the same `_retention_sweep_lifespan`, cancelled alongside the file-retention task on shutdown.

## 4. Known, Deliberately Named Limitations

- **`runtime.agent_traces`** (a different, pre-existing table — the per-agent-step timeline shown in a chat response's `agent_timeline`, not `ObservabilitySpan`'s SLO-monitoring spans) still has no writer at all. That gap predates this document and is out of its scope; it is called out here only so the two concepts are not conflated.
- **No dead-letter or backpressure handling for the pool itself.** `min_size=1, max_size=10` are fixed constants, not configurable via `RuntimeConfig` — a deployment needing different pool sizing has to change the constant in `_build_default_chatbi_application()` directly. This was judged unnecessary complexity to expose as another environment variable before any real deployment has needed to tune it.

## 5. Effort Estimate

Completed in this pass — actuals, not estimates:

| Task | Actual effort |
|---|---|
| `ObservabilityLogStore`/`ObservabilityStore` protocols + retyping existing call sites | ~0.5 day |
| Schema migration (`observability.log_records`/`observability.trace_spans`) | ~0.25 day |
| `PostgresObservabilityLogStore`/`PostgresObservabilityStore` implementation (pooled) + regression tests | ~1 day |
| `RuntimeConfig` flag + `_build_default_chatbi_application()` shared-pool wiring + regression tests | ~0.5 day |
| Pool shutdown (`ChatBIApplication.close()` + lifespan wiring) + regression tests | ~0.5 day |
| Retention sweep (`prune_older_than()` on all four store classes, sweep loop, `RuntimeConfig` field) + regression tests | ~0.75 day |

## 6. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV03-039 | `ObservabilityLogger`/`TraceRecorder` MUST accept any storage backend satisfying the `ObservabilityLogStore`/`ObservabilityStore` protocols (including `replay()`), not only the concrete in-memory classes. | Implemented |
| FR-FV03-040 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` MUST persist every log record and trace span to `observability.log_records`/`observability.trace_spans`, surviving a process restart. | Implemented |
| FR-FV03-041 | Durable observability storage MUST be opt-in via `CHATBI_OBSERVABILITY_POSTGRES_ENABLED` (default off) and MUST be a no-op — falling back to the in-memory defaults — when no `database_url` is configured. | Implemented |
| FR-FV03-042 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` MUST borrow connections from a shared, caller-supplied connection pool rather than opening and closing a new connection per call, and MUST never close a borrowed connection themselves. | Implemented |
| FR-FV03-043 | Durable observability storage MUST be pruned on a schedule (`CHATBI_OBSERVABILITY_RETENTION_DAYS`, default 30), and the `ConnectionPool` `_build_default_chatbi_application()` constructs MUST be released via `ChatBIApplication.close()` on application shutdown. | Implemented |
