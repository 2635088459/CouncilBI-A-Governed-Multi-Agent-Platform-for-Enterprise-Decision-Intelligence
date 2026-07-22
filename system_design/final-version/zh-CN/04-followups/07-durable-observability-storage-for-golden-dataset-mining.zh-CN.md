# 4.7 为 Golden Dataset 挖掘提供持久化的可观测性存储

## 1. 解决的问题

[4.6](06-real-golden-dataset-and-embedding-reload-fix.zh-CN.md) 新增了 `golden_dataset_mining.py`:一套机制,扫描真实聊天查询的问题文本(`ObservabilityLogRecord`),跟带有非零证据数的 `rag_retrieved` trace span(`ObservabilitySpan`)做关联,产出一份人工可审核的真实问题候选清单,用来把 `golden_dataset/cases.json` 从最初手工验证的 24 道题继续扩充下去。那套机制有一个明确写出来的限制:`InMemoryObservabilityLogStore` 和 `InMemoryObservabilityStore`(`observability_logs.py`/`observability.py`)是纯进程内存的字典,没有任何持久化——每条日志和每个 trace span 一重启就没了,所以挖掘机制只能看到"当前这次进程运行期间"问过的问题,永远看不到一个部署真正的历史。本文档补上这个缺口:给这两个 store 都做一个基于 Postgres 的实现,用这个项目已经在 [4.3](03-cross-encoder-reranking.zh-CN.md) 的重排序器和 [4.5](05-pgvector-production-vector-search.zh-CN.md) 的 pgvector 检索上用过的同一套"可选开关"惯例接进去。

## 2. 现状

- `ObservabilityLogger.record()`(`observability_logs.py`)和 `TraceRecorder.record()`/`.run_span()`(`observability.py`)本来就都通过唯一一个存储边界(`self._store`)写入每条日志和每个 trace span——只是到目前为止,这个边界一直只有一个具体的内存实现;可插拔后端的"接口缝"本来就已经存在,只是一直只接了一种实现。
- 每一次聊天请求本来就已经会写好几个 trace span(`REQUEST_RECEIVED`、`SQL_GUARDRAIL_CHECKED`、有证据时的 `RAG_RETRIEVED`、`RESPONSE_SENT`……)加上至少一条带原始(已做 PII 脱敏)问题文本的日志——`application/app.py` 的 `handle_chat_query()` 正是 golden dataset 挖掘最终依赖的那个调用点。
- 这个项目里已有的几个 Postgres 仓储(`PostgresAnalyticsRepository`、`PostgresKnowledgeVectorSource`、`PostgresAuthStore`、`PostgresRagRepository`)已经确立了一个默认关闭的可选 `RuntimeConfig` 开关,决定 `_build_default_chatbi_application()`(`api/http.py`)要不要真的去构造 Postgres 版本——本设计直接复用了这个惯例。它们也都用 `connect_fn(database_url)` + 每次调用现开游标的模式、没有连接池;本设计刻意没有沿用这一点,原因见 §3.3。
- `migrations.py` 的 `V2_SCHEMA_NAMES`/`V2_SCHEMAS_SQL` 已经确立了"一个关注点一个 schema"的惯例(`business`、`semantic`、`runtime`、`governance`、`evaluation`、`knowledge`、`rag`、`analytics`、`auth`)——新增一个 `observability` schema 完全遵循这个惯例,而不是硬塞进某个已有 schema 里。

## 3. 设计

### 3.1 `ObservabilityLogStore`/`ObservabilityStore` 协议

`ObservabilityLogger`/`TraceRecorder` 之前把 `store` 构造参数和属性的类型标注直接写成具体的 `InMemoryObservabilityLogStore`/`InMemoryObservabilityStore` 类。现在两边各自的模块里都多了一个 `Protocol`:

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

`replay()` 被纳入 `ObservabilityStore` 协议本身(而不只是内存实现类上的一个便利方法),是因为 `application/app.py` 的 `handle_observability_trace_detail()` 直接调用了 `self._trace_recorder.store.replay(trace_id)`——任何替换进来的后端都必须支持它。`ChatBIApplication` 自己的 `observability_store`/`observability_log_store` 属性,以及 `golden_dataset_mining.py` 的 `mine_retrieval_labeling_candidates()` 参数,类型标注都从具体类改成了这两个协议——这样内存默认实现、新的 Postgres 实现、以及未来任何其他后端,彼此都能互换,不用改任何调用点。

### 3.2 Schema 迁移

新增一个 `observability` schema,加进 `V2_SCHEMA_NAMES` 和 `BASE_MIGRATION_SQL_STATEMENTS`(不涉及像 [4.5](05-pgvector-production-vector-search.zh-CN.md) 的 pgvector 迁移那样有风险的扩展,比如 `CREATE EXTENSION vector`,所以可以安全地放进基础迁移,不用单独做成可选迁移):

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

两张表都需要一个合成主键(`log_id`/`span_id`),因为 `ObservabilityLogRecord` 和 `ObservabilitySpan` 本身都没有主键字段——`PostgresObservabilityLogStore`/`PostgresObservabilityStore` 在写入时各自生成一个(`f"log_{uuid4().hex}"`/`f"span_{uuid4().hex}"`),不会回写进内存里的 dataclass。`attributes` 用的是 `JSONB`,跟 [4.5](05-pgvector-production-vector-search.zh-CN.md) 的 `vector` 列不一样——Postgres 的 JSON/JSONB 类型是 psycopg 原生支持的(不存在 `vector` 那种缺类型适配器的问题),读回来直接就是普通的 Python 字典,不需要手动解析;写入也只需要对一个 `json.dumps()` 序列化过的字符串做显式 `::jsonb` cast([4.6](06-real-golden-dataset-and-embedding-reload-fix.zh-CN.md) 的种子 SQL 给 `doc_chunks.metadata` 写值时用的就是这个写法),不需要像 [4.5](05-pgvector-production-vector-search.zh-CN.md) 的 `parse_pgvector_embedding()` 那样自己写一个文本格式解析器。

### 3.3 `PostgresObservabilityLogStore` / `PostgresObservabilityStore`

新模块 `observability_postgres.py`,针对上面的 schema 实现这两个协议。跟这个项目其他 Postgres 仓储不一样,这两个**没有**每次调用现开现关一次连接——这是刻意的,不是不一致。光这两个 store,一次聊天请求就要写 3-5 条日志/span,比 `PostgresKnowledgeVectorSource`/`PostgresAnalyticsRepository` 那种每次请求只调用一次的频率高得多;要是这里也用"每次调用开一个新连接"的模式,持续流量下连接开销会成倍放大。所以这两个类改成接受一个 `ConnectionSource`(一个很小的 `Protocol`,只要求有 `.connection() -> AbstractContextManager[Any]`),每次调用从里面**借**一个连接、而不是自己拥有连接:

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

`psycopg_pool.ConnectionPool`直接满足 `ConnectionSource`——它自己的 `.connection()` 上下文管理器已经会在成功时提交、出错时回滚,退出时把连接还回池子里,所以这两个 store 的方法都不需要自己调用 `.commit()` 或 `.close()`(自己调用顶多是多余,要是关掉了借来的连接更是直接毁掉了连接池的意义)。测试里用一个很小的 `FakePool` 实现同一个协议——不需要真实的 Postgres 实例,也不需要真实的 `ConnectionPool`(它背后的重连线程在单元测试里只会是不必要的噪音),就能验证每个方法生成的 SQL 和参数对不对。

### 3.4 接线:一个可选开关,不是默认开启的行为变更

`RuntimeConfig` 新增 `observability_postgres_enabled: bool = False`,从 `CHATBI_OBSERVABILITY_POSTGRES_ENABLED` 读取,完全遵循 [4.3](03-cross-encoder-reranking.zh-CN.md)/[4.5](05-pgvector-production-vector-search.zh-CN.md) 的可选开关惯例。`_build_default_chatbi_application()`(`api/http.py`)只有在开关打开**并且**配置了 `database_url` 时,才会构造**唯一一个** `psycopg_pool.ConnectionPool`,同时交给 `PostgresObservabilityStore` 和 `PostgresObservabilityLogStore`——两边共用一个池,而不是各自维护一套连接,因为它们写的是同一个数据库。开关打开但没配 `database_url` 是个空操作,会退回内存默认实现,跟 [4.5](05-pgvector-production-vector-search.zh-CN.md) 自己那个开关"必须要有真实 Postgres 实例"的保护逻辑一样。`ChatBIApplication` 的构造函数在这次改动之前就已经接受可注入的 `trace_recorder`/`observability_logger` 参数了——那里不需要改,只需要改"到底注入什么"这唯一一个决策点。

### 3.5 连接池的关闭

`ChatBIApplication` 新增一个很小的、通用的 `closeable_resources: tuple[Callable[[], None], ...] = ()` 构造参数,和一个会依次调用每一个的 `close()` 方法——它不是专门为连接池设计的,只是一个通用钩子,给任何这个应用被交到手里、但生命周期不归它自己管的资源用。`_build_default_chatbi_application()` 在构造了连接池时,会把 `observability_connection_pool.close` 注册进去。`create_app()` 现有的 `_retention_sweep_lifespan`(为 [10.3](../10-followups/03-file-retention-and-archival.zh-CN.md) 的文件保留清理任务加的)现在在关闭路径里也会调用 `chatbi_application.close()`——组合进这一个已有的 lifespan,而不是再加一个,因为 FastAPI 每个 router 只保留一个 `lifespan_context`。

### 3.6 数据保留清理

`ObservabilityLogStore`/`ObservabilityStore` 新增一个 `prune_older_than(cutoff_at: datetime) -> int` 方法(四个类都实现了——两个内存实现和两个 Postgres 实现都有,所以清理不是只有 Postgres 才能做的能力)。`RuntimeConfig` 新增 `observability_retention_days: int = 30`(`CHATBI_OBSERVABILITY_RETENTION_DAYS`)。新增的 `_run_observability_retention_sweep_loop()`(`api/http.py`)跟 [10.3](../10-followups/03-file-retention-and-archival.zh-CN.md) 的文件保留清理跑在同一个调度上——一个单进程内的 `asyncio` 循环,不是分布式任务队列,原因跟那个清理任务本来就是单进程循环的原因一样——作为第二个任务,在同一个 `_retention_sweep_lifespan` 里启动,应用关闭时跟文件清理任务一起被取消。

## 4. 明确写出来的已知限制

- **`runtime.agent_traces`**(一张不同的、早就存在的表——聊天回复里 `agent_timeline` 展示的那条按 agent 步骤记录的时间线,不是 `ObservabilitySpan` 那种 SLO 监控 span)现在依然完全没有写入方。这个缺口在本文档之前就存在,不在本文档范围内;这里提一下只是为了避免把这两个概念搞混。
- **连接池本身没有死信或背压处理。** `min_size=1, max_size=10` 是写死的常量,不能通过 `RuntimeConfig` 配置——真要调整池大小的部署得直接改 `_build_default_chatbi_application()` 里的常量。在还没有任何真实部署真的需要调这个参数之前,把它暴露成又一个环境变量被认为是不必要的复杂度。

## 5. 工作量

本轮已完成——以下是实际耗时,不是估算:

| 任务 | 实际耗时 |
|---|---|
| `ObservabilityLogStore`/`ObservabilityStore` 协议 + 改现有调用点的类型标注 | 约 0.5 人天 |
| Schema 迁移(`observability.log_records`/`observability.trace_spans`) | 约 0.25 人天 |
| `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 实现(带连接池) + 回归测试 | 约 1 人天 |
| `RuntimeConfig` 开关 + `_build_default_chatbi_application()` 共享连接池接线 + 回归测试 | 约 0.5 人天 |
| 连接池关闭(`ChatBIApplication.close()` + lifespan 接线) + 回归测试 | 约 0.5 人天 |
| 数据保留清理(四个 store 类都实现 `prune_older_than()`、清理循环、`RuntimeConfig` 字段) + 回归测试 | 约 0.75 人天 |

## 6. 需求编号

| ID | 需求 | 状态 |
|---|---|---|
| FR-FV03-039 | `ObservabilityLogger`/`TraceRecorder` 必须能接受任何满足 `ObservabilityLogStore`/`ObservabilityStore` 协议(包括 `replay()`)的存储后端,而不只是具体的内存类。 | 已实现 |
| FR-FV03-040 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 必须把每条日志和每个 trace span 持久化进 `observability.log_records`/`observability.trace_spans`,能扛过进程重启。 | 已实现 |
| FR-FV03-041 | 持久化的可观测性存储必须通过 `CHATBI_OBSERVABILITY_POSTGRES_ENABLED` 可选开启(默认关闭),并且在没有配置 `database_url` 时必须是空操作——退回内存默认实现。 | 已实现 |
| FR-FV03-042 | `PostgresObservabilityLogStore`/`PostgresObservabilityStore` 必须从一个共享的、调用方传入的连接池借用连接,而不是每次调用都开一个新连接;并且绝不能自己关闭借来的连接。 | 已实现 |
| FR-FV03-043 | 持久化的可观测性存储必须按计划清理(`CHATBI_OBSERVABILITY_RETENTION_DAYS`,默认 30 天),并且 `_build_default_chatbi_application()` 构造的 `ConnectionPool` 必须在应用关闭时通过 `ChatBIApplication.close()` 释放。 | 已实现 |
