# 4.6 真实业务 Golden Dataset,以及一个 Embedding 重复计算的效率修复

## 1. 解决的问题

在 [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md)–[4.5](05-pgvector-production-vector-search.zh-CN.md) 全部实现、测试、并接入运行中的应用之后,一轮代码审查又发现了两个缺口——一个是真实存在的运营成本 bug,另一个是仅靠再多写单元测试也补不上的数据质量缺口:

1. **每次进程重启都会重新计算每个 chunk 的 embedding,即便 [4.5](05-pgvector-production-vector-search.zh-CN.md) 的回填迁移早就算好并持久化了它。** `_load_knowledge_store_from_db()`(`api/http.py`)是进程启动时把线上 `InMemoryKnowledgeStore` 从 Postgres 重建出来的函数,它对每一行 chunk 都无条件调用 `store.embed_text(chunk_text)`——也就是说,不管 `knowledge.doc_embeddings.embedding` 是否已经存了 [4.5](05-pgvector-production-vector-search.zh-CN.md) 回填迁移写进去的那个真实向量,每次重启都要对每个 chunk 真实调用一次 `EmbeddingClient`。除了白白浪费 embedding 服务商的调用成本之外,这还意味着 `PostgresKnowledgeVectorSource` 用来做候选缩窄的向量(数据库里持久化的那个)和 `list_chunk_records()` 用来做最终内存余弦打分的向量(每次重启现算的那个)其实是两个独立算出来的值——它们之所以碰巧一致,只是因为 embedding 模型对相同输入文本是确定性的,而不是有任何机制保证它们必须一致——这是一个潜藏的不一致隐患,不是一个被保证过的结论。
2. **[4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.zh-CN.md) 的 Golden Dataset 完全是编出来的。** `test_retrieval_evaluation.py` 里那 50 道题是一个自成一体、手写的语料库,跟这个平台真实的种子内容(`migrations.py` 的 `KNOWLEDGE_RAG_SEED_SQL`,当时只有 2 篇真实文档)毫无关系。它正确验证了 Hit Rate@K/MRR 这套**机制**——证明 `RetrievalEvaluator` 针对给定标签能算出正确的数字——但完全没有回答"真实用户问真实问题时,这个平台针对自己真实的知识库,能不能召回对的证据"这个问题。一个自造的数据集能验证代码,验证不了检索质量。

本文档同时解决这两个问题:一是对 [4.5](05-pgvector-production-vector-search.zh-CN.md) 重载路径的效率/正确性修复,二是一份真实的、扎根于本平台实际 schema 的、自我验证过的 Golden Dataset——它替换掉了那个自造 fixture,成为 `handle_eval_run()` 生产环境检索指标接线(同一轮代码审查发现的另一半问题,对应 FR-FV03-027 的生产接线缺口)真正打分所依据的数据集。

## 2. 现状

- `PostgresKnowledgeVectorSource.top_chunk_ids()` 和 `backfill_knowledge_embeddings()`(`knowledge_postgres_vector_source.py`,[4.5](05-pgvector-production-vector-search.zh-CN.md))已经能正确读写 `knowledge.doc_embeddings.embedding`(一个 `vector(1536)` 的 pgvector 列),包括 psycopg 需要的 `::vector` 类型转换,因为这个项目里没有注册任何 pgvector 类型适配器。
- `_load_knowledge_store_from_db()`(`api/http.py:620-706`)已经接收一个 `vector_candidate_source: VectorCandidateSource | None` 参数——和 `_build_default_chatbi_application()` 用来判断"这个部署是否已经跑过 [4.5](05-pgvector-production-vector-search.zh-CN.md) 的 pgvector 迁移"的信号完全一致。
- `RetrievalEvaluator`、`hit_rate_at_k()`、`reciprocal_rank()`(`retrieval_evaluation.py`,[4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.zh-CN.md))本身已经正确且测试完备——打分机制不需要改,需要改的只是喂给它的数据。
- `evaluation_cases.py` 的 `load_eval_cases()` 已经能把 JSON/YAML 风格的字典解析成 `EvalCase` 对象,包括 `expected_chunk_ids`——但在这次工作之前,代码库里没有任何地方真的用一个真实的、随包分发的文件去调用它;它此前只在测试里被内联字典调用过。
- `data_model.py` 的 `build_default_data_model_catalog()` 已经定义了这个平台真实的业务表——`orders`、`refunds`、`customers`、`products`、`regions`、`web_events`、`support_tickets`、`marketing_campaigns`——新 Golden Dataset 文档正是扎根在这些领域词汇上,这样数据集读起来像真实业务内容,而不是通用填充文字。

## 3. 设计

### 3.1 读取已持久化的 embedding,而不是重新计算

`_load_knowledge_store_from_db()` 现在根据 `vector_candidate_source` 是否配置分两条路径:

```python
if vector_candidate_source is not None:
    # knowledge.doc_embeddings.embedding 已经为每个回填过的 chunk 存了
    # 真实向量(Spec FV03.5)——直接读回来,而不是重新算。
    cur.execute(
        "SELECT c.chunk_id, c.source_id, c.chunk_index, c.chunk_text, e.embedding::text"
        " FROM knowledge.doc_chunks c"
        " LEFT JOIN knowledge.doc_embeddings e ON e.chunk_id = c.chunk_id"
        " ORDER BY c.source_id, c.chunk_index"
    )
    for chunk_id, source_id, chunk_index, chunk_text, embedding_text in cur.fetchall():
        embedding_vector = (
            parse_pgvector_embedding(embedding_text)
            if embedding_text is not None
            else store.embed_text(chunk_text)  # 还没回填过——退回原方式
        )
        _save_chunk_and_embedding(store, chunk_id, source_id, chunk_index, chunk_text, embedding_vector)
else:
    # 不变:从没跑过 pgvector 迁移的部署,继续用原来"加载时现算"的查询,
    # 永远不会去 SELECT 一个在那边可能压根不存在的列
    # (knowledge.doc_embeddings.embedding)。
    ...
```

有两个设计决定值得单独说明:

- **分支的判断条件是 `vector_candidate_source is not None`,不是另开一个新开关。** 这复用了代码库里其他地方已经在用的、代表"这个部署配置了 pgvector"的同一个信号——这样从没跑过 [4.5](05-pgvector-production-vector-search.zh-CN.md) 迁移的部署,就永远不会去 `SELECT` 一个那边根本不存在的列(`knowledge.doc_embeddings.embedding`),不会让所有没启用 pgvector 的部署每次重启都硬失败。
- **用 `e.embedding::text`,配合新写的 `parse_pgvector_embedding()` 辅助函数解析,而不是依赖原生类型适配器。** 这个项目里没有注册任何 pgvector Python 包([4.5](05-pgvector-production-vector-search.zh-CN.md) §3.2 在写入侧已经确立了这一点);读回这一列同样需要显式 cast + 手动解析,不能假设 psycopg 会怎么表示一个没注册过的类型。
- **持久化的 embedding 是 `NULL` 时,依然退回 `embed_text()`。** 在 [4.5](05-pgvector-production-vector-search.zh-CN.md) 的迁移上线、但回填脚本还没真正跑完这段过渡期里摄入的 chunk,还没有持久化向量;按 chunk 逐个退回(而不是让整个加载失败)保证了这段过渡期是安全的。

### 3.2 十篇新的真实业务文档

真实的种子知识库(`migrations.py` 的 `KNOWLEDGE_RAG_SEED_SQL`)此前只有 2 篇文档——太少了,撑不起一个有意义的 Golden Dataset,而且这两篇都是在这个平台现在这套真实业务表目录(`data_model.py`)成形之前写的。新增的 `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL` 又加了十篇,每一篇都扎根在 `data_model.py` 里某张真实业务表、或这个代码库自己的治理子系统上,让这份数据集读起来像一个真实分析平台真的会维护的内容:

| 文档 | 扎根于 |
|---|---|
| 退款政策与区域物流延迟 | `refunds`、`regions` |
| 营销活动投放与收入归因 | `marketing_campaigns` |
| 产品定价档位变更 | `products` |
| 分析版客户流失分析 | `customers`、`support_tickets` |
| 区域销售差异 | `regions` |
| 网页注册转化漏斗 | `web_events` |
| SQL 防护栏与危险查询策略 | 本代码库自己的 `SimpleSqlGuardrail` |
| 数据治理与 PII 脱敏策略 | 本代码库自己的受限字段审计日志 |
| 事故响应手册 | 本代码库自己的 `agent_traces`/可观测性体系 |
| 评估发布门禁策略 | 本代码库自己的 `ReleaseGatePolicy` |

一共十二篇文档(这十篇加上原有的两篇),和现有的 `KNOWLEDGE_RAG_SEED_SQL` 一起纳入 `BASE_MIGRATION_SQL_STATEMENTS`——都是针对基础迁移已经建好的表执行的、幂等的 `INSERT ... ON CONFLICT DO UPDATE` 语句,和现有种子数据块一样"随时可以安全重跑"。

### 3.3 Golden Dataset 是数据,不是 Python 字面量

二十四道真实业务问题(每篇文档两道)存成了 `src/chatbi/golden_dataset/cases.json`——一个纯 JSON 数组,每个元素是 `{case_id, question, expected_chunk_ids}`——而不是测试文件里的 Python 元组。这带来两个后果:

1. **业务同事编辑一个 JSON、走一次 PR review 就能加题或改题,不用碰 Python 代码。** `evaluation_cases.py` 新增了 `load_golden_dataset_cases()`,一个很薄的封装:读随包分发的文件,再交给已经存在的 `load_eval_cases()` 解析器处理——没有新写解析逻辑,只是给已有逻辑加了个新入口。
2. **这个文件放在 `src/chatbi/` 下,而不是仓库根目录的顶层文件夹。** `Dockerfile.backend` 只 `COPY` `src/` 进生产镜像;如果把数据文件放在别处(比如一个顶层的 `golden_dataset/` 文件夹,虽然那样跟 `spec/`/`system_design/` 的位置更一致),它会悄无声息地永远进不了部署出去的后端。这是一个刻意的放置决定,不是疏忽。

`handle_eval_run()` 的 `_expected_chunk_ids_for_question()`(`application/app.py`)被改成对加载好的数据集做精确的、归一化后的问题文本查找——替换掉了原先两条临时关键词规则(`"revenue" in question and requires_citation(question)`、`"support" in question and "ticket" in question`),那两条规则本来就只是因为当时还没有真实数据集可查才写的权宜之计。这个查找表每个进程只建一次(`lru_cache`),因为随包分发的文件在运行时不会变。

### 3.4 自我验证,而不是断言标签

24 组 `(question, expected_chunk_ids)` 标签,每一组都通过真的构建一个种了这 12 篇文档内容的 `InMemoryKnowledgeStore`、再真的跑一遍 `retrieve()` 来核对过——和 [4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.zh-CN.md) §9 给自己那 50 道题 fixture 立下的规矩完全一样(那次也正是靠这个方法抓到并纠正了一道标错的题)。这次写题过程中也真的抓到了一处标签错误:第一版里一道问"这个月为什么收入突然上涨"的问题,召回结果里营销活动文档排在了本该排第一的收入政策文档前面,因为两篇文档的文本都共享"revenue"、"campaign"、"month"这几个词。把问法改成问"是什么因素导致了收入异常"(而不是"上涨"),消除了这处歧义;这个修复是改了标签的措辞,不是改了打分逻辑。`tests/test_golden_dataset_cases.py` 把这次验证变成了永久的、可重复的检查:它种了一个内容跟 `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL` 完全一致的 store,断言 `RetrievalEvaluator.aggregate()` 对全部 24 道题算出来的 Hit Rate@3 和 MRR 都是 1.0——以后不管是改了数据集还是改了检索管线,只要哪个标签被弄错了,这个测试会先抓到,不会等到生产环境才发现。

## 4. 工作量

这两部分都已经在本轮完成——以下是实际耗时,不是估算:

| 任务 | 实际耗时 |
|---|---|
| Embedding 重载修复(`_load_knowledge_store_from_db()` 分支、`parse_pgvector_embedding()`、回归测试) | 约 0.5 人天 |
| 十篇新业务文档(内容撰写、schema 对齐、种子 SQL) | 约 0.5 人天 |
| 24 道题的 Golden Dataset 撰写 + 自我验证(包括发现并修复的那一处标签错误) | 约 1 人天 |
| JSON 文件 + 加载器 + `handle_eval_run()` 接线改造、回归测试、全量测试验证 | 约 0.5 人天 |

## 5. 需求编号

| ID | 需求 | 状态 |
|---|---|---|
| FR-FV03-035 | 当部署配置了 `VectorCandidateSource` 时,`_load_knowledge_store_from_db()` 必须读取已持久化的 `knowledge.doc_embeddings.embedding` 列;只有当某个 chunk 的持久化 embedding 为 `NULL` 时才退回 `embed_text()` 重新计算。没有配置 pgvector 的部署禁止尝试 `SELECT` 这一列。 | 已实现 |
| FR-FV03-036 | Golden Dataset 必须以外部的、有版本管理的数据文件形式存储(`golden_dataset/cases.json`),通过 `load_golden_dataset_cases()` 加载,不能作为 Python 字面量写在测试代码里。 | 已实现 |
| FR-FV03-037 | Golden Dataset 里每一组 `(question, expected_chunk_ids)` 标签,必须引用 `migrations.py` 真实种进 `knowledge.documents`/`knowledge.doc_chunks` 的文档(不能是一个只存在于内存里的自造 fixture),并且必须在被信任之前,通过真实跑一遍 `retrieve()` 验证过。 | 已实现 |
| FR-FV03-038 | `handle_eval_run()` 的预期 chunk id 查找,必须对加载好的 Golden Dataset做问题文本的精确匹配,不能用临时关键词启发式规则。 | 已实现 |
