# Spec FV03.7:为 Golden Dataset 挖掘提供持久化的可观测性存储

来源设计:
- [4.7 为 Golden Dataset 挖掘提供持久化的可观测性存储 设计](../../../../system_design/final-version/zh-CN/04-followups/07-durable-observability-storage-for-golden-dataset-mining.zh-CN.md)
- [Spec FV03.6:真实业务 Golden Dataset,以及一个 Embedding 重复计算的效率修复](06-real-golden-dataset-and-embedding-reload-fix.spec.zh-CN.md)(`golden_dataset_mining.py`——本 spec 存在的理由——正是那份 spec 的后续机制,用来把 24 道题的数据集继续扩充成真实挖掘出来的问题)
- [Spec FV03.5:用 pgvector 实现生产级向量检索](05-pgvector-production-vector-search.spec.zh-CN.md)(本 spec 的 `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 是全新的、独立的 Postgres 仓储,不是对那份 spec `PostgresKnowledgeVectorSource` 的改动)

---

## 1. 目的

`golden_dataset_mining.py` 这套"把真实的、带 RAG 证据的聊天问题挖出来作为 Golden Dataset 候选"的机制,此前只能看到"当前这次进程运行期间"问过的问题——`InMemoryObservabilityLogStore`/`InMemoryObservabilityStore`(`observability_logs.py`/`observability.py`)是纯进程内存的字典,没有任何持久化。本 spec 给这两个 store 都加一个基于 Postgres 的实现,用 Spec FV03.3/FV03.5 已经在用的同一套 `RuntimeConfig` 开关惯例可选开启,再加上一个持久化、总在写入的 store 需要而内存版不需要的那些运维配套:连接池(光这两个 store,一次聊天请求就要写 3-5 条记录/span)、连接池收尾关闭、以及一个按计划执行的数据保留清理。

## 2. 范围

**范围内:**
- `ObservabilityLogStore`/`ObservabilityStore` 协议,把 `ObservabilityLogger`/`TraceRecorder` 的 `store` 参数/属性、以及 `golden_dataset_mining.py` 的函数参数,从具体的内存类改成协议类型。
- 一个新的 `observability` schema(`observability.log_records`/`observability.trace_spans`),加进基础迁移。
- `PostgresObservabilityLogStore`/`PostgresObservabilityStore`(`observability_postgres.py`),从一个共享的 `ConnectionSource`(连接池)借用连接,而不是每次调用都开一个新连接。
- `RuntimeConfig.observability_postgres_enabled`(可选开关),`_build_default_chatbi_application()` 把一个共享的 `psycopg_pool.ConnectionPool` 接给两个 store。
- `ChatBIApplication.close()`/`closeable_resources`,应用关闭时释放连接池。
- 四个 store 实现都有 `prune_older_than()`,`RuntimeConfig.observability_retention_days`,一个组合进 `create_app()` 现有保留清理 lifespan 里的定时清理任务。

**范围外:**
- 持久化 `runtime.agent_traces`(聊天回复 `agent_timeline` 里那条按 agent 步骤记录的时间线)——一张不同的、早就存在、没有写入方的表,不在本 spec 范围内。
- 连接池大小可配置(`min_size`/`max_size` 是写死的常量)——在还没有任何真实部署真的需要调这个参数之前,被认为是不必要的复杂度。
- 对 `golden_dataset_mining.py` 挖掘逻辑本身(Spec FV03.6)做任何改动——本 spec 只是让它读的那两个 store 变得持久化;挖掘函数自己的过滤/去重逻辑不变。

## 3. 功能需求

| ID | 需求 |
|---|---|
| FR-FV03-039 | `ObservabilityLogger`/`TraceRecorder` 必须能接受任何满足 `ObservabilityLogStore`/`ObservabilityStore` 协议(包括 `replay()`,因为 `handle_observability_trace_detail()` 直接调用它)的存储后端,而不只是具体的内存类。 |
| FR-FV03-040 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 必须分别把每条日志和每个 trace span 持久化进 `observability.log_records`/`observability.trace_spans`,能扛过进程重启。 |
| FR-FV03-041 | 持久化的可观测性存储必须通过 `CHATBI_OBSERVABILITY_POSTGRES_ENABLED` 可选开启(默认 `False`),并且在没有配置 `database_url` 时必须是空操作——退回内存默认实现,跟 Spec FV03.5 给自己开关的保护逻辑一致。 |
| FR-FV03-042 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 必须从一个共享的、调用方传入的 `ConnectionSource` 借用连接,而不是每次调用都开一个新连接;并且不能自己关闭借来的连接。 |
| FR-FV03-043 | 持久化的可观测性存储必须按计划清理(`CHATBI_OBSERVABILITY_RETENTION_DAYS`,默认 30 天),并且 `_build_default_chatbi_application()` 构造的 `ConnectionPool` 必须在应用关闭时通过 `ChatBIApplication.close()` 释放。 |

## 4. 非功能需求

| ID | 需求 |
|---|---|
| NFR-FV03-017 | 对任何以 `observability_postgres_enabled=False`(默认值)构造的 `ChatBIApplication`,`observability_store`/`observability_log_store` 的行为必须跟 Spec FV03.6、本 spec 之前的行为完全一致——对任何没有开启的部署,零行为变化。 |
| NFR-FV03-018 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 每次公开方法调用,必须恰好借出并归还一个连接池连接——不能重复借出,也不能在调用返回后(包括底层 SQL 报错的情况)还留着一个连接没归还。 |

## 5. 数据契约

### 5.1 存储协议

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

### 5.2 Schema 迁移

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

直接加进 `BASE_MIGRATION_SQL_STATEMENTS`(不涉及像 Spec FV03.5 的 `CREATE EXTENSION vector` 那样有风险的扩展)。

### 5.3 带连接池的 Postgres Store

```python
# observability_postgres.py
class ConnectionSource(Protocol):
    def connection(self) -> AbstractContextManager[Any]: ...  # psycopg_pool.ConnectionPool 直接满足


class PostgresObservabilityLogStore:
    def __init__(self, pool: ConnectionSource) -> None:
        self._pool = pool

    def add(self, record: ObservabilityLogRecord) -> None:
        with self._pool.connection() as connection:  # FR-FV03-042:借用,绝不拥有
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO observability.log_records (...) VALUES (..., %(attributes)s::jsonb, ...)",
                    {..., "attributes": json.dumps(dict(record.attributes))},
                )
                # 没有 .commit()/.close() —— 连接池自己的上下文管理器两者都处理了

    def prune_older_than(self, cutoff_at: datetime) -> int:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    "DELETE FROM observability.log_records WHERE recorded_at < %(cutoff_at)s",
                    {"cutoff_at": cutoff_at},
                )
                return cur.rowcount
```

`PostgresObservabilityStore` 结构上完全一样,只是对着 `observability.trace_spans`/`occurred_at`。

### 5.4 接线、收尾关闭与数据保留清理

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


# api/http.py,create_app() 现有的保留清理 lifespan
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
        # ... 等待两个任务结束,吞掉 CancelledError ...
        chatbi_application.close()  # FR-FV03-043
```

## 6. 验收标准

| ID | 标准 |
|---|---|
| AC-FV03-041 | `InMemoryObservabilityLogStore`/`InMemoryObservabilityStore` 和 `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 都满足各自的协议,包括 `prune_older_than()`,以及(对 span 而言)`replay()`。 |
| AC-FV03-042 | `PostgresObservabilityLogStore.add()`/`PostgresObservabilityStore.add_span()` 各自恰好执行一条 `INSERT` 语句,SQL 文本里带 `%(attributes)s::jsonb` cast;`list_by_trace_id()`/`list_spans()`/`list_all()` 能正确地把取回的行还原成 `ObservabilityLogRecord`/`ObservabilitySpan` 实例。 |
| AC-FV03-043 | `_build_default_chatbi_application()` 在 `observability_postgres_enabled=False`(默认)时构造 `InMemoryObservabilityStore`/`InMemoryObservabilityLogStore`;开关为 `True` 且配置了 `database_url` 时构造 Postgres 版本;开关为 `True` 但没有 `database_url` 时,依然构造内存版本(空操作)。 |
| AC-FV03-044 | 对同一个 `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 实例连续调用两次,各自恰好从连接池借出并归还一个连接(两次调用后 `checkout_count == return_count == 2`),且两个方法都从不对借来的连接调用 `.close()`。 |
| AC-FV03-045 | `ChatBIApplication.close()` 调用每一个已注册的 `closeable_resources` 可调用对象;当 `observability_postgres_enabled=True` 时,调用 `close()` 会让构造出来的 `ConnectionPool.closed` 变成 `True`。 |
| AC-FV03-046 | `prune_older_than(cutoff_at)` 只移除严格早于 `cutoff_at` 的记录/span,并返回移除的数量——四个 store 实现表现一致。 |
| AC-FV03-047 | 用一个很短的数据保留清理间隔覆盖值启动一个 `create_app()` 构建的应用,能在启动后不久的这个短窗口内清理掉一条过期的日志记录和一个过期的 trace span,不需要真的等到默认那么长的间隔过去。 |

## 7. 测试计划

### 7.1 单元测试——协议与内存清理

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-065 | 单元 | `InMemoryObservabilityLogStore.prune_older_than()` 只移除 `recorded_at` 早于截止时间的记录,返回值数量正确(AC-FV03-041、AC-FV03-046)。 |
| TC-FV03-066 | 单元 | `InMemoryObservabilityStore.prune_older_than()` 只移除 `occurred_at` 早于截止时间的 span,返回值数量正确(AC-FV03-041、AC-FV03-046)。 |

### 7.2 单元测试——Postgres Store

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-067 | 单元 | 针对一个 fake 连接池/连接,`PostgresObservabilityLogStore.add()` 执行一条 `INSERT`,带 `::jsonb` cast 的 `attributes` 参数(AC-FV03-042)。 |
| TC-FV03-068 | 单元 | 针对 fake 的取回行,`PostgresObservabilityLogStore.list_by_trace_id()`/`.list_all()` 正确还原出 `level`/`attributes`/`recorded_at` 都对的 `ObservabilityLogRecord` 实例(AC-FV03-042)。 |
| TC-FV03-069 | 单元 | `PostgresObservabilityStore.add_span()`/`.list_spans()`/`.replay()`/`.list_all()` 对 span 产出类似的正确 SQL 和往返解析(AC-FV03-041、AC-FV03-042)。 |
| TC-FV03-070 | 单元 | `PostgresObservabilityLogStore.prune_older_than()`/`PostgresObservabilityStore.prune_older_than()` 各自执行一条 `DELETE ... WHERE ... < %(cutoff_at)s` 语句,返回 fake 游标的 `rowcount`(AC-FV03-046)。 |

### 7.3 单元测试——接线、连接池、收尾关闭

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-071 | 单元 | `_build_default_chatbi_application()` 默认构造 `InMemoryObservabilityStore`/`InMemoryObservabilityLogStore`,开关打开且配了 `database_url` 时构造 `PostgresObservabilityStore`/`PostgresObservabilityLogStore`,开关打开但没配 `database_url` 时退回内存版本(AC-FV03-043)。 |
| TC-FV03-072 | 单元 | 对一个背后是 fake 连接池的 store 连续调用两次,报出 `checkout_count == return_count == 2`,而 fake 连接的 `.close()`(如果这个 fake 甚至暴露了这个方法)从未被调用(AC-FV03-044、NFR-FV03-018)。 |
| TC-FV03-073 | 单元 | `ChatBIApplication.close()` 按顺序调用一列 fake 可关闭对象;对一个真实由 `_build_default_chatbi_application()` 在开关打开时构造出来的应用,`close()` 会让底层 `ConnectionPool.closed` 变成 `True`(AC-FV03-045)。 |

### 7.4 集成测试——数据保留清理

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-074 | 集成 | 一个 `create_app()` 构建的 `FastAPI` 应用,配上一个内存 store 里预先种了一条过期、一条最新的日志记录/span、外加一个很短的 `retention_sweep_interval_seconds` 覆盖值的 `ChatBIApplication`,在 `TestClient` 启动后不久,只清理掉过期的那些条目(AC-FV03-047)——照抄了 Spec FV10.3 自己那个文件保留清理集成测试的先例。 |

## 8. 追踪矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV03-039 | AC-FV03-041 | TC-FV03-065、TC-FV03-066、TC-FV03-069 |
| FR-FV03-040 | AC-FV03-042 | TC-FV03-067、TC-FV03-068、TC-FV03-069 |
| FR-FV03-041 | AC-FV03-043 | TC-FV03-071 |
| FR-FV03-042 | AC-FV03-044 | TC-FV03-072 |
| FR-FV03-043 | AC-FV03-045、AC-FV03-046、AC-FV03-047 | TC-FV03-070、TC-FV03-073、TC-FV03-074 |
| NFR-FV03-017 | AC-FV03-043 | TC-FV03-071 |
| NFR-FV03-018 | AC-FV03-044 | TC-FV03-072 |

## 9. 实现说明

- **一处明确写出来的限制,不是悄悄吞掉:** `runtime.agent_traces`(聊天回复自己 `agent_timeline` 里那条按 agent 步骤记录的时间线,跟 `ObservabilitySpan` 的 SLO 监控 span 是不同的表)现在依然完全没有写入方。这个缺口在本 spec 之前就存在,不在本 spec 范围内;这里提一下只是为了避免以后读到的人把这两个概念搞混。
- **第二处明确写出来的限制:** 连接池大小(`min_size=1, max_size=10`)是 `_build_default_chatbi_application()` 里写死的常量,不是 `RuntimeConfig` 字段——在还没有任何真实部署真的需要调这个参数之前,把它暴露成又一个环境变量被认为是不必要的复杂度。
- TC-FV03-074 的集成测试刻意用的是内存 store 实现,不是真实 Postgres——这个项目目前的测试环境里没有可用的真实 Postgres 实例(跟其他地方所有依赖 Postgres 的测试已经被跳过/失败是同一个原因)。清理循环本身(`_run_observability_retention_sweep_loop()`)是后端无关的——它通过 `ObservabilityLogStore`/`ObservabilityStore` 协议调用 `prune_older_than()`,所以这个测试跑的是跟一个 Postgres 部署会跑的完全相同的代码路径,区别只在于具体是哪个 store 实例接住了这些调用。
- FR-FV03-042/AC-FV03-044 那条"绝不能自己关闭借来的连接"的要求,是因为 `psycopg_pool.ConnectionPool.connection()` 自己的上下文管理器已经会在成功时提交、出错时回滚、退出时把连接还回池子——一个 store 方法在这基础上再调用 `.close()`,不只是多余,还会搞乱连接池自己关于"哪些连接可以被复用"的内部记账。
