# Spec FV03.7: Durable Observability Storage for Golden Dataset Mining

Source design:
- [4.7 Durable Observability Storage for Golden Dataset Mining design](../../../../system_design/final-version/en/04-followups/07-durable-observability-storage-for-golden-dataset-mining.en.md)
- [Spec FV03.6: A Real-Business Golden Dataset, and an Embedding-Reload Efficiency Fix](06-real-golden-dataset-and-embedding-reload-fix.spec.en.md) (`golden_dataset_mining.py`, this spec's reason for existing, is that spec's follow-up mechanism for growing the 24-case dataset with real mined questions)
- [Spec FV03.5: Production Vector Search with pgvector](05-pgvector-production-vector-search.spec.en.md) (this spec's `PostgresObservabilityLogStore`/`PostgresObservabilityStore` are new, separate Postgres-backed stores, not a change to that spec's `PostgresKnowledgeVectorSource`)

---

## 1. Purpose

`golden_dataset_mining.py`'s mechanism for surfacing real, RAG-evidenced chat questions as Golden Dataset labeling candidates could only ever see questions asked during the current process's uptime — `InMemoryObservabilityLogStore`/`InMemoryObservabilityStore` (`observability_logs.py`/`observability.py`) are process-local dictionaries with no durability. This spec adds a Postgres-backed implementation of both stores, opt-in via the same `RuntimeConfig`-flag convention Specs FV03.3/FV03.5 already use, plus the operational pieces a durable, always-written store needs that an in-memory one does not: connection pooling (a chat request writes 3–5 records/spans through these stores alone), pool shutdown, and a scheduled retention sweep.

## 2. Scope

**In scope:**
- `ObservabilityLogStore`/`ObservabilityStore` protocols, retyping `ObservabilityLogger`/`TraceRecorder`'s `store` parameter/property and `golden_dataset_mining.py`'s function parameters away from the concrete in-memory classes.
- A new `observability` schema (`observability.log_records`/`observability.trace_spans`) added to the base migration.
- `PostgresObservabilityLogStore`/`PostgresObservabilityStore` (`observability_postgres.py`), borrowing connections from a shared `ConnectionSource` (pool) rather than opening one per call.
- `RuntimeConfig.observability_postgres_enabled` (opt-in flag) and `_build_default_chatbi_application()` wiring a single shared `psycopg_pool.ConnectionPool` into both stores.
- `ChatBIApplication.close()` / `closeable_resources`, releasing the pool on application shutdown.
- `prune_older_than()` on all four store implementations, `RuntimeConfig.observability_retention_days`, and a scheduled sweep composed into `create_app()`'s existing retention-sweep lifespan.

**Out of scope:**
- Persisting `runtime.agent_traces` (the per-agent-step timeline in a chat response's `agent_timeline`) — a different, pre-existing table with no writer, out of this spec's scope.
- Configurable pool sizing (`min_size`/`max_size` are fixed constants) — judged unnecessary complexity before any real deployment has needed to tune them.
- Any change to `golden_dataset_mining.py`'s mining logic itself (Spec FV03.6) — this spec only makes the two stores it reads from durable; the mining function's own filtering/deduplication logic is unchanged.

## 3. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV03-039 | `ObservabilityLogger`/`TraceRecorder` MUST accept any storage backend satisfying the `ObservabilityLogStore`/`ObservabilityStore` protocols (including `replay()`, since `handle_observability_trace_detail()` calls it directly), not only the concrete in-memory classes. |
| FR-FV03-040 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` MUST persist every log record and trace span to `observability.log_records`/`observability.trace_spans` respectively, surviving a process restart. |
| FR-FV03-041 | Durable observability storage MUST be opt-in via `CHATBI_OBSERVABILITY_POSTGRES_ENABLED` (default `False`) and MUST be a no-op — falling back to the in-memory defaults — when no `database_url` is configured, mirroring Spec FV03.5's guard for its own flag. |
| FR-FV03-042 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` MUST borrow connections from a shared, caller-supplied `ConnectionSource` rather than opening and closing a new connection per call, and MUST NOT close a borrowed connection themselves. |
| FR-FV03-043 | Durable observability storage MUST be pruned on a schedule (`CHATBI_OBSERVABILITY_RETENTION_DAYS`, default 30), and the `ConnectionPool` `_build_default_chatbi_application()` constructs MUST be released via `ChatBIApplication.close()` when the application shuts down. |

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV03-017 | For any `ChatBIApplication` constructed with `observability_postgres_enabled=False` (the default), `observability_store`/`observability_log_store` behavior MUST be byte-for-byte identical to Spec FV03.6's pre-Spec-FV03.7 behavior — zero behavior change for any deployment that has not opted in. |
| NFR-FV03-018 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` MUST check out and return exactly one pooled connection per public method call — no double-checkout, and no connection left checked out after the call returns (including when the underlying SQL raises). |

## 5. Data Contracts

### 5.1 Storage Protocols

```python
# observability_logs.py
class ObservabilityLogStore(Protocol):
    def add(self, record: ObservabilityLogRecord) -> None: ...
    def list_by_trace_id(self, trace_id: str) -> tuple[ObservabilityLogRecord, ...]: ...
    def list_all(self) -> tuple[ObservabilityLogRecord, ...]: ...
    def prune_older_than(self, cutoff_at: datetime) -> int: ...  # FR-FV03-043


# observability.py
class ObservabilityStore(Protocol):
    def add_span(self, span: ObservabilitySpan) -> None: ...
    def list_spans(self, trace_id: str) -> tuple[ObservabilitySpan, ...]: ...
    def replay(self, trace_id: str) -> TraceReplay | None: ...  # FR-FV03-039
    def list_all(self) -> tuple[ObservabilitySpan, ...]: ...
    def prune_older_than(self, cutoff_at: datetime) -> int: ...  # FR-FV03-043
```

### 5.2 Schema Migration

```sql
CREATE SCHEMA IF NOT EXISTS observability;
CREATE TABLE IF NOT EXISTS observability.log_records (
    log_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, level TEXT NOT NULL,
    message TEXT NOT NULL, endpoint TEXT NOT NULL, user_id TEXT NOT NULL,
    service TEXT NOT NULL, event TEXT NOT NULL, request_id TEXT,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb, recorded_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observability_log_records_trace_id ON observability.log_records(trace_id);
CREATE TABLE IF NOT EXISTS observability.trace_spans (
    span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, span_name TEXT NOT NULL,
    status TEXT NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
    duration_ms INTEGER CHECK (duration_ms >= 0), attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_observability_trace_spans_trace_id ON observability.trace_spans(trace_id);
```

Added to `BASE_MIGRATION_SQL_STATEMENTS` directly (no risky extension like Spec FV03.5's `CREATE EXTENSION vector` is involved).

### 5.3 Pooled Postgres Stores

```python
# observability_postgres.py
class ConnectionSource(Protocol):
    def connection(self) -> AbstractContextManager[Any]: ...  # psycopg_pool.ConnectionPool satisfies this


class PostgresObservabilityLogStore:
    def __init__(self, pool: ConnectionSource) -> None:
        self._pool = pool

    def add(self, record: ObservabilityLogRecord) -> None:
        with self._pool.connection() as connection:  # FR-FV03-042: borrow, never own
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO observability.log_records (...) VALUES (..., %(attributes)s::jsonb, ...)",
                    {..., "attributes": json.dumps(dict(record.attributes))},
                )
                # no .commit()/.close() — the pool's own context manager handles both

    def prune_older_than(self, cutoff_at: datetime) -> int:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    "DELETE FROM observability.log_records WHERE recorded_at < %(cutoff_at)s",
                    {"cutoff_at": cutoff_at},
                )
                return cur.rowcount
```

`PostgresObservabilityStore` is structurally identical, targeting `observability.trace_spans`/`occurred_at`.

### 5.4 Wiring, Shutdown, and Retention Sweep

```python
# api/http.py, _build_default_chatbi_application()
observability_connection_pool = (
    ConnectionPool(runtime_config.database_url, min_size=1, max_size=10, open=True)
    if runtime_config.observability_postgres_enabled and runtime_config.database_url
    else None
)
trace_recorder = TraceRecorder(
    store=PostgresObservabilityStore(observability_connection_pool)
    if observability_connection_pool is not None else None
)
observability_logger = ObservabilityLogger(
    store=PostgresObservabilityLogStore(observability_connection_pool)
    if observability_connection_pool is not None else None
)
observability_closeable_resources = (
    (observability_connection_pool.close,) if observability_connection_pool is not None else ()
)
# ... ChatBIApplication(..., trace_recorder=..., observability_logger=..., closeable_resources=observability_closeable_resources)


# application/app.py
class ChatBIApplication:
    def __init__(self, ..., closeable_resources: tuple[Callable[[], None], ...] = ()) -> None:
        self._closeable_resources = closeable_resources

    def close(self) -> None:  # FR-FV03-043
        for close_resource in self._closeable_resources:
            close_resource()


# api/http.py, create_app()'s existing retention-sweep lifespan
@asynccontextmanager
async def _retention_sweep_lifespan(_: FastAPI) -> AsyncGenerator[None]:
    task = asyncio.create_task(_run_retention_sweep_loop(retention_worker, retention_sweep_interval_seconds))
    observability_retention_task = asyncio.create_task(
        _run_observability_retention_sweep_loop(
            chatbi_application.observability_log_store,
            chatbi_application.observability_store,
            active_runtime_config.observability_retention_days,
            retention_sweep_interval_seconds,
        )
    )
    try:
        yield
    finally:
        task.cancel(); observability_retention_task.cancel()
        # ... await both, swallowing CancelledError ...
        chatbi_application.close()  # FR-FV03-043
```

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV03-041 | `InMemoryObservabilityLogStore`/`InMemoryObservabilityStore` and `PostgresObservabilityLogStore`/`PostgresObservabilityStore` all satisfy their respective protocols, including `prune_older_than()` and (for spans) `replay()`. |
| AC-FV03-042 | `PostgresObservabilityLogStore.add()`/`PostgresObservabilityStore.add_span()` each execute exactly one `INSERT` statement whose SQL text contains an `%(attributes)s::jsonb` cast; `list_by_trace_id()`/`list_spans()`/`list_all()` correctly round-trip fetched rows back into `ObservabilityLogRecord`/`ObservabilitySpan` instances. |
| AC-FV03-043 | `_build_default_chatbi_application()` with `observability_postgres_enabled=False` (default) constructs `InMemoryObservabilityStore`/`InMemoryObservabilityLogStore`; with the flag `True` and `database_url` configured, constructs the Postgres variants; with the flag `True` and no `database_url`, still constructs the in-memory variants (no-op). |
| AC-FV03-044 | Two consecutive calls against the same `PostgresObservabilityLogStore`/`PostgresObservabilityStore` instance each check out and return exactly one connection from the pool (`checkout_count == return_count == 2` after two calls), and neither method ever calls `.close()` on the borrowed connection. |
| AC-FV03-045 | `ChatBIApplication.close()` calls every registered `closeable_resources` callable; when `observability_postgres_enabled=True`, calling `close()` sets the constructed `ConnectionPool.closed` to `True`. |
| AC-FV03-046 | `prune_older_than(cutoff_at)` removes only records/spans strictly older than `cutoff_at` and returns the count removed, identically on all four store implementations. |
| AC-FV03-047 | Starting a `create_app()`-built application with a short retention-sweep interval override prunes a stale log record and a stale trace span within that short window after startup, without requiring the real default interval to elapse. |

## 7. Test Plan

### 7.1 Unit Tests — Protocols and In-Memory Pruning

| ID | Layer | Description |
|---|---|---|
| TC-FV03-065 | unit | `InMemoryObservabilityLogStore.prune_older_than()` removes only records with `recorded_at` before the cutoff and returns the correct count (AC-FV03-041, AC-FV03-046). |
| TC-FV03-066 | unit | `InMemoryObservabilityStore.prune_older_than()` removes only spans with `occurred_at` before the cutoff and returns the correct count (AC-FV03-041, AC-FV03-046). |

### 7.2 Unit Tests — Postgres Stores

| ID | Layer | Description |
|---|---|---|
| TC-FV03-067 | unit | `PostgresObservabilityLogStore.add()` against a fake pool/connection executes one `INSERT` with an `::jsonb`-cast `attributes` parameter (AC-FV03-042). |
| TC-FV03-068 | unit | `PostgresObservabilityLogStore.list_by_trace_id()`/`.list_all()` against fake fetched rows reconstruct `ObservabilityLogRecord` instances with correct `level`/`attributes`/`recorded_at` (AC-FV03-042). |
| TC-FV03-069 | unit | `PostgresObservabilityStore.add_span()`/`.list_spans()`/`.replay()`/`.list_all()` produce analogous correct SQL and round-trip parsing for spans (AC-FV03-041, AC-FV03-042). |
| TC-FV03-070 | unit | `PostgresObservabilityLogStore.prune_older_than()`/`PostgresObservabilityStore.prune_older_than()` each execute one `DELETE ... WHERE ... < %(cutoff_at)s` statement and return the fake cursor's `rowcount` (AC-FV03-046). |

### 7.3 Unit Tests — Wiring, Pooling, and Shutdown

| ID | Layer | Description |
|---|---|---|
| TC-FV03-071 | unit | `_build_default_chatbi_application()` constructs `InMemoryObservabilityStore`/`InMemoryObservabilityLogStore` by default, `PostgresObservabilityStore`/`PostgresObservabilityLogStore` when the flag is set with a `database_url`, and falls back to in-memory when the flag is set without one (AC-FV03-043). |
| TC-FV03-072 | unit | Two consecutive calls against a store backed by a fake pool report `checkout_count == return_count == 2`, and the fake connection's `.close()` (if the fake even exposes one) is never called (AC-FV03-044, NFR-FV03-018). |
| TC-FV03-073 | unit | `ChatBIApplication.close()` calls a list of fake closeable callables in order; against a real `_build_default_chatbi_application()`-constructed application with the flag enabled, `close()` sets the underlying `ConnectionPool.closed` to `True` (AC-FV03-045). |

### 7.4 Integration Test — Retention Sweep

| ID | Layer | Description |
|---|---|---|
| TC-FV03-074 | integration | A `create_app()`-built `FastAPI` app, constructed with a `ChatBIApplication` whose in-memory stores are pre-seeded with one stale and one recent log record/span and a short `retention_sweep_interval_seconds` override, prunes only the stale entries shortly after `TestClient` startup (AC-FV03-047) — mirrors Spec FV10.3's own file-retention-sweep integration test precedent. |

## 8. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV03-039 | AC-FV03-041 | TC-FV03-065, TC-FV03-066, TC-FV03-069 |
| FR-FV03-040 | AC-FV03-042 | TC-FV03-067, TC-FV03-068, TC-FV03-069 |
| FR-FV03-041 | AC-FV03-043 | TC-FV03-071 |
| FR-FV03-042 | AC-FV03-044 | TC-FV03-072 |
| FR-FV03-043 | AC-FV03-045, AC-FV03-046, AC-FV03-047 | TC-FV03-070, TC-FV03-073, TC-FV03-074 |
| NFR-FV03-017 | AC-FV03-043 | TC-FV03-071 |
| NFR-FV03-018 | AC-FV03-044 | TC-FV03-072 |

## 9. Implementation Notes

- **A named limitation, not a silent one:** `runtime.agent_traces` (the per-agent-step timeline in a chat response's own `agent_timeline`, a different table from `ObservabilitySpan`'s SLO-monitoring spans) still has no writer at all. That gap predates this spec and is out of its scope; it is called out here only so the two concepts are not conflated by a future reader.
- **A second named limitation:** pool sizing (`min_size=1, max_size=10`) is a fixed constant in `_build_default_chatbi_application()`, not a `RuntimeConfig` field — judged unnecessary complexity to expose as another environment variable before any real deployment has needed to tune it.
- TC-FV03-074's integration test deliberately uses the in-memory store implementations, not real Postgres — this project has no live Postgres instance available in its current test environment (the same reason every Postgres-dependent test elsewhere is already skipped/failing there). The sweep loop itself (`_run_observability_retention_sweep_loop()`) is backend-agnostic — it calls `prune_older_than()` through the `ObservabilityLogStore`/`ObservabilityStore` protocols, so this test exercises the identical code path a Postgres-backed deployment would run, differing only in which concrete store receives the calls.
- FR-FV03-042/AC-FV03-044's "never close a borrowed connection" requirement exists because `psycopg_pool.ConnectionPool.connection()`'s own context manager already commits on success, rolls back on error, and returns the connection to the pool on exit — a store method calling `.close()` on top of that would not merely be redundant, it would corrupt the pool's own bookkeeping of which connections are available for reuse.
