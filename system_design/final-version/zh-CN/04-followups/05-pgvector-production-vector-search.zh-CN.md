# 4.5 用 pgvector 实现生产级向量检索

## 1. 解决的问题

[4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md)–[4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.zh-CN.md) 建立的一切,都跑在 `InMemoryKnowledgeStore` 的进程内字典上:每个 embedding 只存在于内存里,进程一重启整个索引就没了,没有近似最近邻(ANN)索引(检索就是对每个存储向量做线性扫描),也无法在多个后端副本之间共享。本文档把存储层和向量检索层换成平台现有 Postgres 实例上的 pgvector,同时刻意不动 BM25 打分([4.2](02-bm25-keyword-scoring.zh-CN.md))、cross-encoder 重排序([4.3](03-cross-encoder-reranking.zh-CN.md))和评估工具([4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.zh-CN.md))——本阶段只改变*向量存在哪里、怎么找到最近的那些*,不改变找到之后怎么打分。

**对本文档初稿的修正:** 早前版本把目标定在 `rag.documents`/`rag.chunks`/`rag.embedding_metadata`(`rag_postgres_rows.py`)和 `VectorStore` 协议(`embedding_vector_rag.py`)上。但那些属于另一条独立的纯向量证据管线(`EmbeddingVectorRagService`/`InMemoryVectorRagRetriever`)——[4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md) 已经刻意把这条管线从编排器的线上聊天查询路径里退役,换成了 `InMemoryKnowledgeStore` 的混合路径。所以"生产级向量检索"这个阶段真正应该对准的,是 `InMemoryKnowledgeStore` 自己背后的表——`knowledge.documents`/`knowledge.doc_chunks`/`knowledge.doc_embeddings`(`migrations.py:372-410`)——而不是那条已退役管线的 schema。下面 §2–§3 已按此修正。

## 2. 现状梳理

- `knowledge.documents`/`knowledge.doc_chunks`/`knowledge.doc_embeddings`(`migrations.py:372-410`,`KNOWLEDGE_RAG_TABLES_SQL`)才是 `_load_knowledge_store_from_db()`(`api/http.py`)在启动时读取、用来填充线上 `InMemoryKnowledgeStore` 的真实 Postgres 表——也就是 `RagAgentRunner` 实际查询的那个 store。`knowledge.doc_embeddings` 只存 `embedding_model`、`embedding_dimensions`,以及一个 `vector_ref TEXT`——一个文本引用,从来不是向量本身。目前这套 schema 里没有任何 `vector` 类型的列,也没有 `pgvector` 扩展。
- `migrations.py:509,529`(`vector_ref` 的示例值)以及 `files/promotion.py:224` 对应位置的字符串 `"pgvector://..."` 是占位/示例值,不是真正的客户端集成——项目里目前没有任何 pgvector 客户端库依赖。
- `InMemoryKnowledgeStore.list_chunk_records()`(`knowledge.py:218-255`)是目前唯一真正落地当前权限模型的地方——`owner_user_id`、`allowed_roles`、`doc_type`/`doc_types`、`tags`,以及 `shared_visibility_resolver` 钩子(Spec FV10.1/FV10.2)——而且完全是在 Python 里、对内存中每个 chunk 逐一执行的。今天没有任何一部分是用 SQL 表达的。
- 一旦 [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md) 把它接进 `InMemoryKnowledgeStore.embed_text()`,`OpenAIEmbeddingClient`(`embedding_vector_config.py:19-63`,`text-embedding-3-small` 对应1536维)就已经能生成真实 embedding——本阶段消费的是这个输出,不需要自己再生成一遍 embedding。

## 3. 设计方案

### 3.1 Schema 迁移

给 `knowledge.doc_embeddings` 加一个真正的向量列和索引,按项目现有的迁移惯例(`migrations.py`):

```sql
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE knowledge.doc_embeddings
    ADD COLUMN embedding vector(1536);

CREATE INDEX IF NOT EXISTS knowledge_doc_embeddings_hnsw_idx
    ON knowledge.doc_embeddings
    USING hnsw (embedding vector_cosine_ops);
```

`embedding` 一开始允许为空(现有的行还没有向量——见3.4节)。选 HNSW 而不是 IVFFlat:这个项目的语料库规模小到 HNSW 的构建成本完全不是问题,而且 HNSW 在同等查询延迟下召回率更好,也不需要像 IVFFlat 那样预先按语料规模调 `lists` 参数。这一列放在 `knowledge.doc_embeddings` 上而不是 `knowledge.doc_chunks` 上,是因为这张表本来就是按 `(chunk_id, embedding_model)` 一行的粒度设计的——这正是"某一个具体 embedding"的自然粒度,如果平台以后需要用两个不同模型并存地给同一个 chunk 做 embedding(比如模型迁移期间),这个粒度是有意义的,一 chunk 一行反而不够用。

### 3.2 `PostgresKnowledgeVectorSource`

新增模块,比如 `knowledge_postgres_vector_source.py`。这**不是**现有 `VectorStore` 协议(`embedding_vector_rag.py`)的一个实现——那个协议的 `search()` 返回的是为已退役纯向量管线设计的 `EvidenceChunk`,它的 `org_id`/`permission_tags` 过滤模型也对不上 `InMemoryKnowledgeStore` 真正的 `owner_user_id`/`allowed_roles`/`shared_visibility_resolver` 权限模型。改用一个新的、更窄的协议:

```python
class VectorCandidateSource(Protocol):
    def top_chunk_ids(
        self,
        *,
        query_vector: tuple[float, ...],
        requesting_user_id: str,
        user_role: str | None,
        doc_type: str | None,
        doc_types: tuple[str, ...],
        limit: int,
    ) -> tuple[tuple[str, float], ...]:  # (chunk_id, cosine_distance) 对
        ...


class PostgresKnowledgeVectorSource:
    def __init__(self, connection_factory: Callable[[], Connection]) -> None:
        self._connection_factory = connection_factory

    def top_chunk_ids(self, *, query_vector, requesting_user_id, user_role, doc_type, doc_types, limit):
        # SELECT c.chunk_id, e.embedding <=> %(query_vector)s AS distance
        # FROM knowledge.doc_embeddings e
        # JOIN knowledge.doc_chunks c ON c.chunk_id = e.chunk_id
        # JOIN knowledge.documents d ON d.source_id = c.source_id
        # WHERE e.embedding IS NOT NULL
        #   AND (d.owner_user_id IS NULL OR d.owner_user_id = %(requesting_user_id)s)
        #   AND (%(user_role)s IS NULL OR d.allowed_roles = '{}' OR %(user_role)s = ANY(d.allowed_roles))
        #   AND (%(doc_type)s IS NULL OR d.doc_type = %(doc_type)s)
        #   AND (%(doc_types)s = '{}' OR d.doc_type = ANY(%(doc_types)s))
        # ORDER BY e.embedding <=> %(query_vector)s
        # LIMIT %(limit)s
        ...
```

`owner_user_id`/`allowed_roles`/`doc_type` 过滤跑在 **SQL 的 `WHERE` 子句内部**,不是在 Python 里做检索后过滤——这是一个刻意的、不可协商的设计选择,不是风格偏好:[10.1 RAG 单用户隔离](../10-followups/01-rag-per-user-isolation.zh-CN.md) 记录了这个平台知识库里一次真实发生过的跨租户数据泄漏事故,起因正是这一类错误(过滤是在检索之后做的,而不是在查询本身的作用域里做的)。

**明确记录下来、而不是悄悄丢掉的已知缺口:** `shared_visibility_resolver` 钩子(Spec FV10.2 的文件共享授权)是一个没有 SQL 表示的 Python 回调——上面的 `top_chunk_ids()` 不会把可见性授予一份"被分享但非本人拥有"的文档。本阶段的验收标准(§3.5)只覆盖 SQL 能表达的 owner/role/doc_type 过滤;把 Spec FV10.2 的分享授权也变成一张可查询的表(这样 `PostgresKnowledgeVectorSource` 才能 JOIN 它),不在本阶段范围内,应该是 Spec FV10.2 自己的后续工作,而不是在这里被默默吸收掉。

### 3.3 接入统一后的检索路径

[4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md) 已经让 `InMemoryKnowledgeStore` 的混合路径(BM25+向量+来源权重融合,再经过 [4.3](03-cross-encoder-reranking.zh-CN.md) 的重排序)成为线上聊天查询唯一可达的检索机制。本阶段不会重新引入第二条路径——而是让*这一条路径内部的"生成向量候选"这一步*变得可插拔,同时 `list_chunk_records()` 今天在 Python 里已经强制执行的每一条权限过滤(§2)继续原样跑在返回的候选集合上:

1. `InMemoryKnowledgeStore` 新增一个可选的构造参数 `vector_candidate_source: VectorCandidateSource | None`。设置了它时,`retrieve()` 会调用它,拿到当前查询的 `requesting_user_id`/`user_role`/`doc_type`/`doc_types` 对应的 top-N `(chunk_id, distance)` 候选,再和 `list_chunk_records()` 现有、不变的 Python 端过滤结果取交集(由于 §3.2 的已知缺口,这个交集步骤仍然是必需的——Postgres 侧的来源只是一个收窄候选范围的预过滤,不是权限判定的最终权威)。
2. `vector_candidate_source` 为 `None` 时(今天的行为,以及现有的每一个测试),`retrieve()` 保持不变——内存里的线性余弦扫描照旧运行。
3. `_rank_records()` 的 BM25 项([4.2](02-bm25-keyword-scoring.zh-CN.md))和融合公式两种情况下都不受影响——它们本来就只是在 `list_chunk_records()`/上面交集步骤产出的候选集合上运行。

### 3.4 回填迁移

一个一次性脚本,不属于请求处理路径的一部分:对每一个目前只在内存路径里建过索引的 chunk(也就是每一行 `embedding IS NULL` 的 `knowledge.doc_embeddings` 记录),通过 `InMemoryKnowledgeStore.embed_text()` 调用 [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md) 里接入的真实 `EmbeddingClient`,把算出来的向量 `UPDATE` 回该行。按批次执行以遵守 embedding provider 的速率限制(`OpenAIEmbeddingClient` 本来就会为每次调用上报 `token_count`/`estimated_cost`,回填脚本可以把这些记下来做成本可视化)。这个脚本的形态和项目里现有的、通过 `migrate.py`/`migrations.py` 跑的其他一次性修复/回填任务是一样的。

### 3.5 Owner 隔离验证

因为 [10.1](../10-followups/01-rag-per-user-isolation.zh-CN.md) 记录了这个平台真实发生过的一次同类失败,本阶段的验收标准里明确包含一个跨用户测试:seed 两个用户各自拥有、内容有重叠的文档,断言限定在用户 A `requesting_user_id` 范围内的 `PostgresKnowledgeVectorSource.top_chunk_ids()` 调用,永远不会返回属于用户 B 私有文档的 chunk——而且要针对实际执行的 SQL 验证(确认 `WHERE d.owner_user_id ...` 谓词确实存在),而不是只检查返回结果集——一个"先查全部再在 Python 里过滤"的实现,同样能通过一个只看返回结果集的断言。由于 §3.2 的已知缺口(共享可见性),这个测试刻意**不**声称和 `list_chunk_records()` 完整权限模型完全对等——只保证已经实现的 owner/role/doc_type 过滤本身的作用域是对的。

## 4. 工作量评估

大约 **4–6 人天**(比初稿的 3.5–5 人天上调,因为修正后的目标需要和 `InMemoryKnowledgeStore` 的 Python 端权限模型对齐,而不是直接照搬一个基于 `org_id` 的现成协议):

| 任务 | 估算 |
|---|---|
| 迁移:`pgvector` 扩展、`knowledge.doc_embeddings` 新列、HNSW 索引 | 0.5 天 |
| `PostgresKnowledgeVectorSource` 实现 + 一致性测试 | 1.5–2 天 |
| 让 `InMemoryKnowledgeStore.retrieve()` 内部"生成向量候选"这一步变得可插拔,包括和现有 Python 端过滤取交集 | 1–1.5 天 |
| 回填脚本(通过 `embed_text()` 为现有 chunk 重新 embedding 并回填) | 0.5–1 天 |
| Owner 隔离测试(3.5节)及常规回归验证 | 0.5–1 天 |

## 5. 需求编号

| ID | 需求 | 状态 |
|---|---|---|
| FR-FV03-029 | 必须启用 `pgvector` 扩展,`knowledge.doc_embeddings` 必须携带一个带 HNSW 索引的 `vector` 类型列。 | 已实现 |
| FR-FV03-030 | `PostgresKnowledgeVectorSource` 必须实现本文档定义的 `VectorCandidateSource` 协议——不是已退役纯向量管线里那个不相关的 `VectorStore` 协议。 | 已实现 |
| FR-FV03-031 | `owner_user_id`、`allowed_roles`、`doc_type`/`doc_types` 的作用域限定必须在 SQL 查询内部完成,不能是应用代码里检索之后的过滤。共享可见性(Spec FV10.2 的授权)是本阶段明确排除在外的已知缺口(§3.2)。 | 已实现 |
| FR-FV03-032 | `InMemoryKnowledgeStore.retrieve()` 内部"生成向量候选"这一步,必须能通过一个可选构造参数在内存扫描和 `PostgresKnowledgeVectorSource` 之间切换,且不改动 BM25 打分、融合或重排序逻辑;`retrieve()` 现有的 Python 端权限过滤必须继续跑在返回的候选集合之上。 | 已实现 |
| FR-FV03-033 | 必须有一次回填迁移,为本阶段之前摄入的每个 chunk 填充真实 embedding 向量;必须有一个 owner 隔离测试,在这个存储对外服务真实流量之前验证 SQL 层面的 `owner_user_id` 作用域限定。 | 已实现 |
