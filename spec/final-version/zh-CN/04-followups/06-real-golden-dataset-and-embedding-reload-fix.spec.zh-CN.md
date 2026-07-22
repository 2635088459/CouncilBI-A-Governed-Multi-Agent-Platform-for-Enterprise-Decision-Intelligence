# Spec FV03.6:真实业务 Golden Dataset,以及一个 Embedding 重复计算的效率修复

来源设计:
- [4.6 真实业务 Golden Dataset,以及一个 Embedding 重复计算的效率修复 设计](../../../../system_design/final-version/zh-CN/04-followups/06-real-golden-dataset-and-embedding-reload-fix.zh-CN.md)
- [Spec FV03.4:检索侧的标注数据集与 Hit Rate/MRR 自动化评估](04-golden-dataset-hit-rate-and-mrr-evaluation.spec.zh-CN.md)(本 spec 把那份 spec 里自造的 50 题 fixture 换成一份真实的、扎根于 schema 的数据集——`hit_rate_at_k()`、`reciprocal_rank()`、`RetrievalEvaluator` 本身不变)
- [Spec FV03.5:用 pgvector 实现生产级向量检索](05-pgvector-production-vector-search.spec.zh-CN.md)(本 spec 的 embedding 重载修复,读的正是 `PostgresKnowledgeVectorSource` 早就写进去的那个向量;`parse_pgvector_embedding()` 把那份 spec 建立的 `::vector` cast 规矩,从写入侧原样搬到了读取侧)

---

## 1. 目的

Spec FV03.1–FV03.5 全部实现、测试、并接入运行中的应用之后,一轮代码审查发现了两个进一步的缺口:`_load_knowledge_store_from_db()` 每次进程重启都通过真实的 `EmbeddingClient` 重新计算每个 chunk 的 embedding,即便 Spec FV03.5 的回填迁移早就算好并持久化了那个确切的向量;而 Spec FV03.4 的 Golden Dataset 是一个完全编出来的 50 题 fixture,跟这个平台真实的种子内容毫无关系,所以它只验证了 Hit Rate@K/MRR 这套**机制**,完全没有回答检索质量本身的问题。本 spec 修复重载路径,并把这个自造数据集换成一份真实的、扎根于 schema 的、自我验证过的数据集。

## 2. 范围

**范围内:**
- 当配置了 `vector_candidate_source`(Spec FV03.5)时,读取已持久化的 `knowledge.doc_embeddings.embedding` 列,而不是重新计算。
- `migrations.py` 种子数据里新增十篇真实业务文档,扎根于这个平台真实的业务表和治理子系统。
- 一份 24 道题的 Golden Dataset,以外部 JSON 文件(`golden_dataset/cases.json`)存储,通过 `load_golden_dataset_cases()` 加载。
- 把 `handle_eval_run()` 的预期 chunk id 查找,接到加载好的 Golden Dataset 上,按问题文本精确匹配。
- 自我验证:每一条标签都通过真的对真实种子内容跑一遍 `retrieve()` 来核对过。

**范围外:**
- 对 `RetrievalEvaluator`、`hit_rate_at_k()`、`reciprocal_rank()`、或 `EvaluationScorer` 的指标拆解接线(Spec FV03.4)做任何改动——本 spec 只改喂给这套不变机制的**数据**。
- 对 `PostgresKnowledgeVectorSource` 的查询逻辑、`pgvector` schema、或回填迁移本身(Spec FV03.5)做任何改动——本 spec 只是给那个迁移早就在写的向量加了一条读取路径。
- 挖掘真实生产问题来进一步扩充 Golden Dataset——那是 Spec FV03.7 的事。
- 把 Golden Dataset 持久化到 Postgres,或者给它建一个后台编辑界面——这个文件放在 `src/chatbi/golden_dataset/cases.json` 正是为了让"编辑 JSON + PR review"就是完整的工作流程;不在本 spec 范围内加任何额外工具。

## 3. 功能需求

| ID | 需求 |
|---|---|
| FR-FV03-035 | 当部署配置了 `VectorCandidateSource` 时,`_load_knowledge_store_from_db()` 必须读取已持久化的 `knowledge.doc_embeddings.embedding` 列;只有当某个 chunk 的持久化 embedding 为 `NULL` 时才退回 `embed_text()` 重新计算。没有配置 pgvector 的部署(`vector_candidate_source is None`)禁止尝试 `SELECT` 这一列,并且必须精确复现本 spec 之前的查询和行为。 |
| FR-FV03-036 | Golden Dataset 必须以外部的、有版本管理的数据文件形式存储(`golden_dataset/cases.json`),通过 `load_golden_dataset_cases()` 加载,不能作为 Python 字面量写在测试或应用代码里。 |
| FR-FV03-037 | Golden Dataset 里每一组 `(question, expected_chunk_ids)` 标签,必须引用 `migrations.py` 真实种进 `knowledge.documents`/`knowledge.doc_chunks` 的文档(不能是一个只存在于内存里的自造 fixture),并且必须在被信任之前,通过真实跑一遍 `retrieve()` 验证过。 |
| FR-FV03-038 | `handle_eval_run()` 的预期 chunk id 查找,必须对加载好的 Golden Dataset 做问题文本的精确匹配(大小写不敏感、去除首尾空白),不能用临时关键词启发式规则。没有精确匹配的问题必须返回空元组,让该用例退出检索打分(跟 `expected_sql_fragments` 现有惯例一致)。 |

## 4. 非功能需求

| ID | 需求 |
|---|---|
| NFR-FV03-015 | 对任何 `vector_candidate_source` 为 `None` 的 `InMemoryKnowledgeStore` 重载场景,`_load_knowledge_store_from_db()` 的查询和结果 store 状态,必须跟本 spec 之前的行为完全一致——对任何没有启用 Spec FV03.5 pgvector 检索的部署,零行为变化。 |
| NFR-FV03-016 | 完整的 24 道题 Golden Dataset,针对一个种了 `migrations.py` 的 `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL` 写进生产环境的确切内容的 `InMemoryKnowledgeStore` 跑一遍,必须得出 Hit Rate@3 = MRR = 1.0——达不到这个标准的标签是标注缺陷,不是可以接受的数据集条目。 |

## 5. 数据契约

### 5.1 `_load_knowledge_store_from_db()` 的重载分支

```python
def _load_knowledge_store_from_db(
    connect_fn: Callable[[str], Any],
    database_url: str,
    embedding_client: EmbeddingClient | None = None,
    reranker: CrossEncoderReranker | None = None,
    vector_candidate_source: VectorCandidateSource | None = None,
) -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore(
        embedding_client=embedding_client, reranker=reranker,
        vector_candidate_source=vector_candidate_source,
    )
    try:
        conn = connect_fn(database_url)
        with conn.cursor() as cur:
            # ... documents 的 SELECT 不变 ...
            if vector_candidate_source is not None:  # FR-FV03-035
                cur.execute(
                    "SELECT c.chunk_id, c.source_id, c.chunk_index, c.chunk_text,"
                    " e.embedding::text"
                    " FROM knowledge.doc_chunks c"
                    " LEFT JOIN knowledge.doc_embeddings e ON e.chunk_id = c.chunk_id"
                    " ORDER BY c.source_id, c.chunk_index"
                )
                for chunk_id, source_id, chunk_index, chunk_text, embedding_text in cur.fetchall():
                    embedding_vector = (
                        parse_pgvector_embedding(embedding_text)
                        if embedding_text is not None
                        else store.embed_text(chunk_text)  # NULL —— 还没回填过
                    )
                    _save_chunk_and_embedding(store, chunk_id, source_id, chunk_index, chunk_text, embedding_vector)
            else:  # NFR-FV03-015:查询和行为都不变
                cur.execute(
                    "SELECT chunk_id, source_id, chunk_index, chunk_text"
                    " FROM knowledge.doc_chunks ORDER BY source_id, chunk_index"
                )
                for chunk_id, source_id, chunk_index, chunk_text in cur.fetchall():
                    _save_chunk_and_embedding(store, chunk_id, source_id, chunk_index, chunk_text, store.embed_text(chunk_text))
    except Exception:
        pass  # 数据库还没就绪;退回空 store
    return store
```

`parse_pgvector_embedding(value: str) -> tuple[float, ...]`(`knowledge_postgres_vector_source.py`)解析 pgvector 的标准文本输出(`"[0.1,0.2,0.3]"`)——跟 Spec FV03.5 为写入建立的 `::vector`/`::text` cast 规矩一样,只是这次用在读取侧,因为这个项目里没有注册任何 pgvector Python 类型适配器。

### 5.2 Golden Dataset 文件和加载器

```python
# evaluation_cases.py
_GOLDEN_DATASET_CASES_PATH = Path(__file__).parent / "golden_dataset" / "cases.json"

def load_golden_dataset_cases(path: Path | None = None) -> tuple[EvalCase, ...]:
    """FR-FV03-036/037:加载真实业务检索 Golden Dataset。每一组
    (question, expected_chunk_ids) 都通过真的跑一遍 retrieve() 对照
    真实种子内容验证过。"""

    active_path = path or _GOLDEN_DATASET_CASES_PATH
    raw_cases = json.loads(active_path.read_text(encoding="utf-8"))
    return load_eval_cases(raw_cases)  # 复用现有解析器,不变
```

`golden_dataset/cases.json` 放在 `src/chatbi/` 下,而不是仓库根目录顶层文件夹,是因为 `Dockerfile.backend` 只 `COPY` `src/` 进生产镜像(FR-FV03-036)。

`migrations.py` 的 `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL`(加进了 `BASE_MIGRATION_SQL_STATEMENTS`)里新增十篇文档,每一篇都扎根于 `data_model.py` 业务目录里一张真实的表(`refunds`、`marketing_campaigns`、`products`、`customers`/`support_tickets`、`regions`、`web_events`)或本代码库自己的治理子系统(SQL guardrail、PII 脱敏、发布门禁),加上原有的两篇——一共十二篇。

### 5.3 `handle_eval_run()` 的预期 chunk id 查找

```python
@lru_cache(maxsize=1)
def _golden_dataset_expected_chunk_ids_by_question() -> Mapping[str, tuple[str, ...]]:
    return {
        case.question.strip().lower(): case.expected_chunk_ids
        for case in load_golden_dataset_cases()
    }


class ChatBIApplication:
    def _expected_chunk_ids_for_question(self, question: str) -> tuple[str, ...]:
        # FR-FV03-038:精确匹配,不是关键词启发式规则
        return _golden_dataset_expected_chunk_ids_by_question().get(question.strip().lower(), ())
```

## 6. 验收标准

| ID | 标准 |
|---|---|
| AC-FV03-034 | `_load_knowledge_store_from_db()` 在配置了 `vector_candidate_source`、且某个 chunk 的持久化 `embedding` 非 `NULL` 时,该 chunk 的 `ChunkEmbedding.embedding_vector` 来自 `parse_pgvector_embedding()` 的输出,并且从不为该 chunk 调用配置好的 `EmbeddingClient`。 |
| AC-FV03-035 | 同上,针对持久化 `embedding` 为 `NULL` 的 chunk,退回 `store.embed_text(chunk_text)`,恰好为该 chunk 调用一次配置好的 `EmbeddingClient`。 |
| AC-FV03-036 | `_load_knowledge_store_from_db()` 在 `vector_candidate_source=None` 时执行原来的 `SELECT chunk_id, source_id, chunk_index, chunk_text ...` 查询(不引用 `embedding` 列),产出跟本 spec 之前实现一致的 store 状态。 |
| AC-FV03-037 | `load_golden_dataset_cases()` 从随包分发的 JSON 文件里加载出恰好 24 个 `EvalCase` 对象,每个都有非空的 `case_id`、`question`、`expected_chunk_ids`,且没有重复的 `case_id`。 |
| AC-FV03-038 | 全部 24 个已加载用例的 `expected_chunk_ids` 条目,都引用了十二篇真实种子文档(`KNOWLEDGE_RAG_SEED_SQL` + `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL`)里存在的 `chunk_id`。 |
| AC-FV03-039 | 针对一个种了跟十二篇真实文档一致内容的 `InMemoryKnowledgeStore`,`RetrievalEvaluator` 对完整 24 道题数据集算出的 `retrieval_hit_rate == 1.0` 且 `retrieval_mrr == 1.0`。 |
| AC-FV03-040 | 对一个跟 24 道 Golden Dataset 问题之一精确匹配(大小写不敏感、去除首尾空白)的问题,`_expected_chunk_ids_for_question()` 返回正确的 `expected_chunk_ids`;对任何不匹配的问题返回 `()`。 |

## 7. 测试计划

### 7.1 单元测试——Embedding 重载

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-058 | 单元 | 针对一个 fake 游标、返回非 `NULL` 的 `embedding::text` 值,`_load_knowledge_store_from_db()` 通过 `parse_pgvector_embedding()` 填充该 chunk 的 embedding,并且从不调用一个"被调用就报错"的 fake `EmbeddingClient`(AC-FV03-034)。 |
| TC-FV03-059 | 单元 | 同上,`embedding::text` 值为 `NULL` 时,恰好调用一次 fake `EmbeddingClient`,并使用它返回的向量(AC-FV03-035)。 |
| TC-FV03-060 | 单元 | `_load_knowledge_store_from_db()` 在 `vector_candidate_source=None` 时执行原来形状的查询,针对现有测试套件已经用过的同一份 fixture 数据,精确复现本 spec 之前的 store 状态(AC-FV03-036,NFR-FV03-015)。 |

### 7.2 单元测试——Golden Dataset 加载与有效性

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-061 | 单元 | `load_golden_dataset_cases()` 返回 24 个用例,`case_id` 互不重复,每个用例的 `expected_chunk_ids` 都非空(AC-FV03-037)。 |
| TC-FV03-062 | 单元 | 全部已加载用例的 `expected_chunk_ids` 条目,都属于一份镜像十二篇真实种子文档的已知 chunk-id 集合(AC-FV03-038)。 |
| TC-FV03-063 | 单元 | 针对一个种了十二篇真实文档确切内容的 store,`RetrievalEvaluator.evaluate()`/`.aggregate()` 对完整数据集报出 `retrieval_hit_rate == 1.0` 且 `retrieval_mrr == 1.0`(AC-FV03-039,NFR-FV03-016)。 |

### 7.3 单元测试——预期 chunk id 查找

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-064 | 单元 | `handle_eval_run()` 针对一个跟 Golden Dataset 自己某道题精确匹配的问题,对一个种了对应真实文档的 live `InMemoryKnowledgeStore` 打分,`metric_breakdown` 里算出非 `None` 的 `retrieval_hit_rate`/`retrieval_mrr`;一个问题都不匹配 Golden Dataset 任何条目的套件,则完全不出现这两个 key(AC-FV03-040)。 |

## 8. 追踪矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV03-035 | AC-FV03-034、AC-FV03-035 | TC-FV03-058、TC-FV03-059 |
| FR-FV03-036 | AC-FV03-037 | TC-FV03-061 |
| FR-FV03-037 | AC-FV03-038、AC-FV03-039 | TC-FV03-062、TC-FV03-063 |
| FR-FV03-038 | AC-FV03-040 | TC-FV03-064 |
| NFR-FV03-015 | AC-FV03-036 | TC-FV03-060 |
| NFR-FV03-016 | AC-FV03-039 | TC-FV03-063 |

## 9. 实现说明

- 撰写过程中发现并修正的那一处真实标签错误(第一版里一道问"收入为什么突然上涨"的问题,召回结果里营销活动文档排在了本该排第一的收入政策文档前面,因为两篇文档都共享"revenue"/"campaign"/"month"这几个词)本身不是一条单独编号的验收标准——真正抓到它的是 NFR-FV03-016"必须得 1.0"这条硬性标准,而且它确实抓到了。
- `golden_dataset/cases.json` 放在 `src/chatbi/` 下、而不是一个更符合 `spec/`/`system_design/` 位置习惯的顶层 `golden_dataset/` 文件夹,是来源设计 §3.3 里记录的一个刻意的放置决定,不是疏忽——已经对照 `Dockerfile.backend` 的 `COPY src ./src` 那一行验证过。
- 本 spec 刻意没有去顺手修复 `runtime.agent_traces` 没有写入方的问题,也没有用真实生产问题扩充 Golden Dataset——前者是一个明确记录、不在本 spec 范围内的缺口,后者留给了 Spec FV03.7(挖掘),都不是悄悄折进本 spec 验收标准里的隐藏工作。
