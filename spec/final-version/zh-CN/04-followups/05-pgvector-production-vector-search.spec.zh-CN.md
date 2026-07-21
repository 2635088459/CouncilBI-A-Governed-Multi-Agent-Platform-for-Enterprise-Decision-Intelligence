# Spec FV03.5:用 pgvector 实现生产级向量检索

来源设计:
- [4.5 用 pgvector 实现生产级向量检索设计](../../../../system_design/final-version/zh-CN/04-followups/05-pgvector-production-vector-search.zh-CN.md)(它的 §1 记录了一次在 Spec FV03.1–FV03.4 实现完之后做出的 schema 目标修正——本 spec 反映的是修正后的设计,不是最初的草稿)
- [Spec FV03.1:统一"纯向量"与"混合检索"两条路径,并接入真实 Embedding](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.zh-CN.md)(本 spec 的 `PostgresKnowledgeVectorSource` 是那份 spec 原则上已经预留可插拔的"生成向量候选"步骤的第二种实现——在这里它才真正变得可插拔)
- [Spec FV10.1:RAG 单用户隔离](../10-followups/01-rag-per-user-isolation.spec.zh-CN.md)(本 spec 的 owner 隔离验收标准,直接沿用那份 spec 修复过的跨租户泄漏问题——同一类错误,应用在一条新的代码路径上)

---

## 1. 目的

`InMemoryKnowledgeStore` 的向量检索是一次对进程本地、纯内存字典的无索引线性扫描:进程一重启就丢失所有 embedding,多个后端副本之间也无法共享。本 spec 在 `knowledge.doc_embeddings`——`InMemoryKnowledgeStore` 启动时本来就从这张真实表填充数据——上加入基于 pgvector 的存储和 ANN 检索,作为内存扫描的一个可选、可插拔的替代品,同时不动 BM25 打分(Spec FV03.2)、融合和重排序(Spec FV03.3)。

## 2. 范围

**范围内:**
- 在 `knowledge.doc_embeddings` 上启用 `pgvector` 扩展、新增一个 `vector` 类型列,并建 HNSW 索引。
- 一个 `VectorCandidateSource` 协议,以及它的实现 `PostgresKnowledgeVectorSource`,查询 `knowledge.doc_embeddings`/`knowledge.doc_chunks`/`knowledge.documents`,在 SQL 里完成 `owner_user_id`/`allowed_roles`/`doc_type` 的作用域限定。
- 在 `InMemoryKnowledgeStore` 上新增一个可选的构造参数 `vector_candidate_source`,`retrieve()` 用它在 `list_chunk_records()` 现有的 Python 端权限过滤**运行之前**先收窄候选集合——是收窄,不是取代。
- 一个回填脚本,为每一行已存在的 `knowledge.doc_embeddings` 记录填充 `embedding`。
- 一个验证 SQL 层面 `owner_user_id` 作用域限定的 owner 隔离测试。

**范围外:**
- 共享可见性的 SQL 支持(Spec FV10.2 的文件共享授权)——`PostgresKnowledgeVectorSource` 不会把可见性授予一份"被分享但非本人拥有"的文档;这是一个明确记录下来的缺口(§9),不是悄悄留下的。
- BM25 打分(Spec FV03.2)、融合权重或重排序(Spec FV03.3)的任何改动——本 spec 只改变向量候选从哪来。
- 已退役的纯向量管线(`VectorStore`、`EmbeddingVectorRagService`、`InMemoryVectorRagRetriever`)——完全不动;`PostgresKnowledgeVectorSource` 实现的是另一个全新协议。
- 去掉 `_load_knowledge_store_from_db()` 启动时把整个语料库一次性加载进程内存的做法——本 spec 让向量*检索*本身达到生产级(用 ANN 代替线性扫描),但不解决"整个语料库仍然一次性存在一个 Python 字典里"这个独立问题(§9)。

## 3. 功能需求

| ID | 需求 |
|---|---|
| FR-FV03-029 | 必须启用 `pgvector` 扩展,`knowledge.doc_embeddings` 必须携带一个带 HNSW 索引(`vector_cosine_ops`)的 `vector` 类型 `embedding` 列。 |
| FR-FV03-030 | `PostgresKnowledgeVectorSource` 必须实现本 spec 定义的 `VectorCandidateSource` 协议——不是已退役纯向量管线用的那个不相关的 `VectorStore` 协议。 |
| FR-FV03-031 | `owner_user_id`、`allowed_roles`、`doc_type`/`doc_types` 的作用域限定必须在 `PostgresKnowledgeVectorSource` 的 SQL 查询内部完成,不能是应用代码里检索之后的过滤。共享可见性(Spec FV10.2 的授权)明确不在本条需求范围内(§9)。 |
| FR-FV03-032 | `InMemoryKnowledgeStore.retrieve()` 必须支持一个可选的 `vector_candidate_source`。设置了它时,必须把候选集合收窄到 `top_chunk_ids()` 返回的 chunk id,并且是与(而不是取代)`list_chunk_records()` 现有、不变的 Python 端权限过滤取交集。未设置时,`retrieve()` 的行为必须和本 spec 之前完全一致。 |
| FR-FV03-033 | 必须有一次回填迁移,通过 `InMemoryKnowledgeStore.embed_text()` 为每一行当前 `embedding` 为 `NULL` 的 `knowledge.doc_embeddings` 记录填充向量。在这个来源被用于生产之前,必须有一个 owner 隔离测试验证 SQL 层面的 `owner_user_id` 作用域限定。 |
| FR-FV03-034 | 若 `vector_candidate_source.top_chunk_ids()` 抛出异常,`retrieve()` 必须回退到现有的内存候选生成方式,而不是让异常继续传播或让请求失败——和 Spec FV03.3 的重排序回退已经建立的"降级而不是崩溃"姿态一致。 |

## 4. 非功能需求

| ID | 需求 |
|---|---|
| NFR-FV03-013 | 对任何未配置 `vector_candidate_source` 构造的 `InMemoryKnowledgeStore`,`retrieve()` 的输出(候选集合、排序、evidence 列表)必须和本 Spec FV03.5 之前的行为逐字节一致——对任何未主动选用这项能力的现有部署或测试,行为零改变。 |
| NFR-FV03-014 | 每次 `retrieve()` 调用,`PostgresKnowledgeVectorSource.top_chunk_ids()` 最多只能被调用一次——不能为单次请求产生重复的 Postgres 往返。 |

## 5. 数据契约

### 5.1 Schema 迁移

```sql
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE knowledge.doc_embeddings
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

CREATE INDEX IF NOT EXISTS knowledge_doc_embeddings_hnsw_idx
    ON knowledge.doc_embeddings
    USING hnsw (embedding vector_cosine_ops);
```

加进 `migrations.py` 里现有的 `KNOWLEDGE_RAG_TABLES_SQL`,和现有的 `knowledge.*` DDL 放在一起,而不是单独一个迁移文件——匹配本项目现有的"每个 schema 一整块"的惯例。

### 5.2 `VectorCandidateSource` 协议与 `PostgresKnowledgeVectorSource`

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
    ) -> tuple[tuple[str, float], ...]:  # (chunk_id, cosine_distance),按距离从近到远
        ...


class PostgresKnowledgeVectorSource:
    """FR-FV03-030/031:knowledge.* schema,owner_user_id/allowed_roles/doc_type
    的作用域限定在 SQL 里完成。不实现已退役管线的 VectorStore 协议,
    也不会授予共享可见性访问权限(§9)。"""

    def __init__(self, connection_factory: Callable[[], Connection]) -> None:
        self._connection_factory = connection_factory

    def top_chunk_ids(
        self,
        *,
        query_vector: tuple[float, ...],
        requesting_user_id: str,
        user_role: str | None,
        doc_type: str | None,
        doc_types: tuple[str, ...],
        limit: int,
    ) -> tuple[tuple[str, float], ...]:
        connection = self._connection_factory()
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT c.chunk_id, e.embedding <=> %(query_vector)s AS distance
                FROM knowledge.doc_embeddings e
                JOIN knowledge.doc_chunks c ON c.chunk_id = e.chunk_id
                JOIN knowledge.documents d ON d.source_id = c.source_id
                WHERE e.embedding IS NOT NULL
                  AND (d.owner_user_id IS NULL OR d.owner_user_id = %(requesting_user_id)s)
                  AND (
                    %(user_role)s IS NULL
                    OR d.allowed_roles = '{}'
                    OR %(user_role)s = ANY(d.allowed_roles)
                  )
                  AND (%(doc_type)s IS NULL OR d.doc_type = %(doc_type)s)
                  AND (%(doc_types)s = '{}' OR d.doc_type = ANY(%(doc_types)s))
                ORDER BY e.embedding <=> %(query_vector)s
                LIMIT %(limit)s
                """,
                {
                    "query_vector": list(query_vector),
                    "requesting_user_id": requesting_user_id,
                    "user_role": user_role,
                    "doc_type": doc_type,
                    "doc_types": list(doc_types),
                    "limit": limit,
                },
            )
            rows = cur.fetchall()
        return tuple((row[0], float(row[1])) for row in rows)
```

### 5.3 `InMemoryKnowledgeStore` 接入

```python
class InMemoryKnowledgeStore:
    def __init__(
        self,
        shared_visibility_resolver=None,
        embedding_client=None,
        reranker=None,
        vector_candidate_source: "VectorCandidateSource | None" = None,  # FR-FV03-032
    ) -> None:
        ...
        self._vector_candidate_source = vector_candidate_source

    def retrieve(self, query: RetrievalQuery, trace_id: str = "") -> RetrievalResult:
        filtered_records = self.list_chunk_records(...)  # 不变,FR-FV03-032 的权威来源
        filtered_records = self._narrow_by_vector_candidates(filtered_records, query)
        ranked_records = self._rank_records(filtered_records, query)
        ...  # 从这里开始不变(Spec FV03.2/FV03.3)

    def _narrow_by_vector_candidates(
        self,
        filtered_records: tuple[KnowledgeChunkRecord, ...],
        query: RetrievalQuery,
    ) -> tuple[KnowledgeChunkRecord, ...]:
        """FR-FV03-032/034:是和 list_chunk_records() 自己的权限过滤取交集,
        而不是取代它。任何错误都不会额外收窄(原样回退到 filtered_records),
        而不是让请求失败。"""

        if self._vector_candidate_source is None:
            return filtered_records
        query_embedding = query.query_embedding or text_embedding(query.question)
        try:
            candidates = self._vector_candidate_source.top_chunk_ids(
                query_vector=query_embedding,
                requesting_user_id=query.requesting_user_id,
                user_role=query.user_role,
                doc_type=query.doc_type,
                doc_types=query.doc_types,
                limit=max(query.top_k * 4, 20),
            )
        except Exception:
            return filtered_records
        candidate_chunk_ids = {chunk_id for chunk_id, _ in candidates}
        return tuple(
            record for record in filtered_records if record.chunk.chunk_id in candidate_chunk_ids
        )
```

### 5.4 回填脚本

```python
def backfill_knowledge_embeddings(
    connection_factory: Callable[[], Connection],
    embedding_client: EmbeddingClient,
    batch_size: int = 50,
) -> int:
    """FR-FV03-033:通过与 Spec FV03.1 接入的同一个 embedding client(经
    embed_text() 等效路径),为每一行当前为 NULL 的 knowledge.doc_embeddings
    记录填充 embedding——不是另开一条 embedding 代码路径。返回更新的行数。"""
```

## 6. 验收标准

| ID | 标准 |
|---|---|
| AC-FV03-027 | 迁移 SQL 文本包含 `CREATE EXTENSION IF NOT EXISTS vector`、一条给 `knowledge.doc_embeddings` 加 `vector(1536)` 列的 `ALTER TABLE`,以及一条 `CREATE INDEX ... USING hnsw` 语句。 |
| AC-FV03-028 | `PostgresKnowledgeVectorSource.top_chunk_ids()` 恰好执行一条 SQL 语句,其文本引用了 `owner_user_id`、`allowed_roles` 和 `<=>` 距离运算符。 |
| AC-FV03-029 | 对 `tests/test_knowledge_store.py` 里现有的回归 fixture,用 `vector_candidate_source=None` 构造的 `InMemoryKnowledgeStore` 产出的 `retrieve()` 结果(候选集合、排序、evidence 列表)和本 Spec FV03.5 之前的实现完全一致。 |
| AC-FV03-030 | 用一个只返回子集 chunk id 的 fake `vector_candidate_source` 构造的 `InMemoryKnowledgeStore`,把 `retrieve()` 的候选集合收窄到该子集,并且是与(而不是取代)现有权限过滤后的集合取交集。 |
| AC-FV03-031 | 若 `vector_candidate_source.top_chunk_ids()` 抛出异常,`retrieve()` 依然用完整的权限过滤候选集合返回一个正确的、非错误结果,而不是让异常继续传播。 |
| AC-FV03-032 | 回填脚本更新每一行 `embedding IS NULL` 的 `knowledge.doc_embeddings` 记录,且不会给已经有非空 `embedding` 的行重新做 embedding。 |
| AC-FV03-033 | 限定在用户 A `requesting_user_id` 范围内的 `PostgresKnowledgeVectorSource.top_chunk_ids()` 调用,永远不会返回属于另一个用户 B 所拥有文档的 chunk id——通过检查实际执行的 SQL 和参数来验证,而不是只看返回的行。 |

## 7. 测试计划

### 7.1 单元测试——Schema 与 SQL 构造

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-049 | unit | 迁移 SQL 常量包含 `pgvector` 扩展语句、`ALTER TABLE knowledge.doc_embeddings` 加列语句,以及 HNSW 索引语句(AC-FV03-027)。 |
| TC-FV03-050 | unit | 针对一个 fake connection,`PostgresKnowledgeVectorSource.top_chunk_ids()` 恰好执行一条 SQL 语句,其文本包含 `owner_user_id`、`allowed_roles` 和 `<=>`(AC-FV03-028, NFR-FV03-014)。 |
| TC-FV03-051 | unit | `top_chunk_ids()` 按取回顺序解析 `(chunk_id, distance)` 行,不做二次排序——SQL 自身的 `ORDER BY` 是唯一的排序权威。 |

### 7.2 单元测试——`InMemoryKnowledgeStore` 接入

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-052 | unit | `vector_candidate_source=None` 时,`retrieve()` 原样复现 `tests/test_knowledge_store.py` 里本 Spec FV03.5 之前全部现有测试的断言(AC-FV03-029, NFR-FV03-013)。 |
| TC-FV03-053 | unit | 对一个五 chunk 的权限过滤集合,配一个只返回其中两个 chunk 的 fake `vector_candidate_source`,`retrieve()` 只对该子集打分并返回(AC-FV03-030)。 |
| TC-FV03-054 | unit | 配一个(模拟 SQL 作用域限定出错、错误地)返回请求者看不见的文档 chunk id 的 fake `vector_candidate_source`,最终结果依然排除该 chunk——证明 `list_chunk_records()` 的 Python 端过滤仍然是权威判定,而不只是附加过滤(为 FR-FV03-032"取交集而不是取代"这句话提供纵深防御证明)。 |
| TC-FV03-055 | unit | 配一个会抛异常的 fake `vector_candidate_source`,`retrieve()` 回退到完整的权限过滤候选集合,依然返回正确的 evidence,而不是抛出异常(AC-FV03-031)。 |

### 7.3 单元测试——回填

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-056 | unit | 针对一个混合了 `NULL` 和已填充 `embedding` 行的 fake connection,`backfill_knowledge_embeddings()` 只更新 `NULL` 的那些行,每更新一行调用一次 embedding client(AC-FV03-032)。 |

### 7.4 单元测试——Owner 隔离

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-057 | unit | 用 `requesting_user_id="user_a"` 调用 `top_chunk_ids()`,执行的 SQL 捕获到的参数里包含绑定到 `owner_user_id` 谓词的 `"user_a"`——针对一个记录已执行 SQL/参数的 fake connection 验证,遵循本项目现有的 `FakeRagPostgresConnection` 风格测试替身惯例(AC-FV03-033)。 |

## 8. 追踪矩阵

| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV03-029 | AC-FV03-027 | TC-FV03-049 |
| FR-FV03-030 | AC-FV03-028 | TC-FV03-050, TC-FV03-051 |
| FR-FV03-031 | AC-FV03-033 | TC-FV03-057 |
| FR-FV03-032 | AC-FV03-029, AC-FV03-030 | TC-FV03-052, TC-FV03-053, TC-FV03-054 |
| FR-FV03-033 | AC-FV03-032, AC-FV03-033 | TC-FV03-056, TC-FV03-057 |
| FR-FV03-034 | AC-FV03-031 | TC-FV03-055 |
| NFR-FV03-013 | AC-FV03-029 | TC-FV03-052 |
| NFR-FV03-014 | — | TC-FV03-050 |

## 9. 实现说明

- **明确记录、而不是悄悄留下的缺口:** `PostgresKnowledgeVectorSource` 不会把可见性授予一份通过 Spec FV10.2 审批流程分享、但请求者本人并不拥有的文档——`top_chunk_ids()` 的 SQL 只表达了 `owner_user_id`/`allowed_roles`/`doc_type` 这几个已经有列可查的过滤条件。TC-FV03-054 就是刻意设计来证明:即便 SQL 过滤有遗漏或过宽,Python 端的 `list_chunk_records()` 过滤依然会兜底——正因为这个缺口存在,本 spec 才不敢声称和完整权限模型 SQL 层面对等,只保证收窄这一步永远不会让访问范围超出 `list_chunk_records()` 已经允许的范围。
- **第二个明确记录的缺口:** 本 spec 让*检索*这一步达到生产级(HNSW ANN 索引代替 O(n) 线性扫描),但没有解决 `_load_knowledge_store_from_db()` 启动时把每个文档/chunk/embedding 都加载进一个进程本地 Python 字典这件事——如果语料库规模大到真的需要 pgvector 的 ANN 检索,那么每个后端副本都把整个语料库加载进内存,本身就是一道本 spec 没有拆除的真实扩展性天花板。这是本 spec 刻意排除在范围之外的后续工作,不是遗漏。
- FR-FV03-034 的回退逻辑(§5.3 里裸的 `except Exception`)完全照搬 Spec FV03.3 重排序器的回退方式,理由相同:Postgres 连接或查询失败没法预先枚举完,而降级到现有的内存候选集合永远是安全的,不会比直接让请求失败更差。
- TC-FV03-057 的 owner 隔离测试刻意是一个针对 fake connection(捕获已执行的 SQL/参数)的单元测试,而不是针对真实数据库的集成测试——本项目当前的 CI/测试环境里没有可用的 Postgres 实例(现有的每一个依赖 Postgres 的测试,在这个环境里都因为同样的原因被跳过或失败,已经证实了这一点)。本 spec 的验收标准限定在"fake connection 测试真正能证明的东西"上:正确的 SQL 被构造出来、参数被正确绑定。等真的有 Postgres 实例可用时,针对本 spec 的迁移和查询做一次真实数据库验证,是本 spec 自己的测试计划无法替代的一个部署验证步骤。
