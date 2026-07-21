# Spec FV03.1：统一"纯向量"与"混合检索"两条路径，并接入真实 Embedding

来源设计：
- [4.1 统一"纯向量"与"混合检索"两条路径,并接入真实 Embedding 设计](../../../../system_design/final-version/zh-CN/04-followups/01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md)
- [Spec FV-03：Embedding 与 Vector RAG](../03-embedding-vector-rag.spec.zh-CN.md)（父 spec；本 spec 把它已经定义的 `EmbeddingClient`/`VectorStore` 契约(FR-FV03-001)扩展到一条父 spec 未覆盖到的、既有的第二条检索路径上）

---

## 1. 目的

`RagAgentRunner.run()` 目前会根据是否注入了 `vector_retriever`，走进两种互斥检索机制中的一种：一条是没有关键词打分的纯向量路径，另一条是混合(关键词+向量)路径——但它存储的向量是确定性哈希分桶占位实现，从来不是真实 embedding 模型的输出。本 spec 让混合路径成为线上聊天查询唯一可达的路径，并给它接上真实 embedding，使父 spec FV-03 已经定义好的组件真正在生产环境的相关性排序里发挥作用。

## 2. 范围

**范围内：**
- 在 `InMemoryKnowledgeStore.__init__` 和 `ingest_document()` 上增加可选的 `embedding_client: EmbeddingClient | None` 参数，传入时用于 chunk embedding。
- 把 `OpenAIEmbeddingClient`(父 Spec FV-03 §5 已定义)接入知识库摄入调用点，通过现有的 `runtime_config.embedding_provider` 开关控制。
- 修改主编排器构造 `RagAgentRunner` 的方式，始终传入 `vector_retriever=None`。

**范围外：**
- 对父 Spec FV-03 定义的 `VectorStore`/`EmbeddingClient` 协议签名的任何改动。
- 删除 `InMemoryVectorRagRetriever` 或 `_retrieve_vector_if_possible()`——`rag_v2.py`/`api/http.py` 那条独立的证据管线可以继续独立于编排器的 `RagAgentRunner` 构造和使用它们。
- 关键词打分的任何改动(Spec FV03.2 负责 BM25)或重排序的任何改动(Spec FV03.3)。
- 重新调优 `0.60`/`0.35`/`source_score` 融合权重——推迟到 Spec FV03.4，等有了标注评估基线之后再做。

## 3. 功能需求

| ID | 需求 |
|---|---|
| FR-FV03-014 | `InMemoryKnowledgeStore` 必须支持可选的 `embedding_client: EmbeddingClient \| None = None` 构造参数,以及 `ingest_document()` 上一个等效的可选参数。任一处传入时(方法级参数优先),chunk embedding 必须调用 `embedding_client.embed(...)` 并存储返回的向量。两处都未传入时,必须保持现有的确定性哈希分桶 `text_embedding()` 行为不变。 |
| FR-FV03-015 | 知识库摄入调用点必须读取纯向量管线选择 embedding provider 时已经在用的同一份 `runtime_config.embedding_provider`/`runtime_config.embedding_model` 配置(父 Spec FV-03 §5.5),使一个配置开关同时决定两个调用点的 provider。 |
| FR-FV03-016 | 主编排器构造 `RagAgentRunner` 时必须始终传入 `vector_retriever=None`,确保 `_retrieve_if_possible()`(混合路径)是线上 `POST /api/v2/chat/query` 请求路由到 RAG agent 时唯一可达的检索机制。 |
| FR-FV03-017 | 本次改动不得让 `tests/test_knowledge_store.py` 或 `tests/test_rag_agent.py` 中任何现有测试回归——这些测试继续省略 `embedding_client`,并且必须继续原样验证确定性哈希分桶 embedding 路径。 |

## 4. 非功能需求

| ID | 需求 |
|---|---|
| NFR-FV03-005 | 对于永远不会到达 RAG agent 的请求(例如未被分类为 RAG 意图的纯 SQL 问题),`RagAgentRunner.run()` 的行为必须不受 FR-FV03-016 影响——本次改动只限定在 `RagAgentRunner` 内部走哪条分支,不涉及它上游的路由逻辑。 |
| NFR-FV03-006 | 用真实的 `embedding_client` 调用 `InMemoryKnowledgeStore.ingest_document()`,不得改变它的返回类型、对 `_chunks_by_chunk_id` 产生的副作用,或它返回的 `KnowledgeChunkRecord` 元组的形状——改变的只是存储的 embedding *值*,不是摄入契约本身。 |

## 5. 数据契约

### 5.1 `InMemoryKnowledgeStore` 构造函数与摄入逻辑

```python
class InMemoryKnowledgeStore:
    def __init__(
        self,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._embedding_client = embedding_client
        # 现有的 _documents_by_source_id / _chunks_by_chunk_id / _embeddings_by_chunk_id 不变

    def ingest_document(
        self,
        document: KnowledgeDocument,
        raw_text: str,
        chunk_size: int = 90,
        chunk_overlap: int = 15,
        embedding_client: EmbeddingClient | None = None,
    ) -> tuple[KnowledgeChunkRecord, ...]:
        """FR-FV03-014：方法级的 embedding_client 参数优先于构造函数级的;
        两者都未提供时,回退到现有的确定性 text_embedding()。"""
        active_client = embedding_client or self._embedding_client
        ...
        for index, text in enumerate(chunks, start=1):
            vector = (
                active_client.embed(EmbeddingRequest(input_texts=(text,))).vectors[0]
                if active_client is not None
                else text_embedding(text)
            )
            embedding = ChunkEmbedding(
                embedding_id=f"{document.source_id}_embedding_{index}",
                chunk_id=chunk.chunk_id,
                embedding_vector=vector,
            )
            ...
```

### 5.2 编排器接线

```python
# 线上聊天查询路径的编排器接线
rag_agent_runner = RagAgentRunner(
    knowledge_store=knowledge_store,
    vector_retriever=None,  # FR-FV03-016：混合路径是唯一可达的路径
    ...
)
```

### 5.3 由运行时配置驱动的摄入接线

```python
def build_knowledge_store_embedding_client(
    runtime_config: RuntimeConfig,
) -> EmbeddingClient | None:
    """FR-FV03-015：复用 build_embedding_vector_rag_service_from_runtime_config()
    (父 Spec FV-03 §5.5)已经在读取的同一个 provider 开关。"""
    if runtime_config.embedding_provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = runtime_config.embedding_model or "text-embedding-3-small"
        return OpenAIEmbeddingClient(api_key=api_key, model=model)
    if runtime_config.embedding_provider == "mock":
        return None  # ingest_document() 回退到 text_embedding()
    raise ValueError(f"Unsupported embedding provider: {runtime_config.embedding_provider}")
```

## 6. 验收标准

| ID | 标准 |
|---|---|
| AC-FV03-009 | `InMemoryKnowledgeStore(embedding_client=SomeRealClient()).ingest_document(...)` 存储的 `ChunkEmbedding.embedding_vector` 等于该 chunk 文本对应的 `SomeRealClient().embed(...).vectors[0]`,而不是哈希分桶 `text_embedding()` 的输出。 |
| AC-FV03-010 | `InMemoryKnowledgeStore().ingest_document(...)`(任何地方都未提供 `embedding_client`)存储的 `embedding_vector` 值,与本 spec 改动前完全一致——对固定输入文本,和改动前的确定性哈希分桶输出逐字节相同。 |
| AC-FV03-011 | 一个到达 RAG agent 的线上 `chat_query_v2` 请求,永远不会走进 `_retrieve_vector_if_possible()` 分支——通过断言构造时 `RagAgentRunner.vector_retriever is None`,并确认针对 spy/mock `InMemoryKnowledgeStore` 时 `retrieve()`(混合路径)被执行来验证。 |
| AC-FV03-012 | 设置 `runtime_config.embedding_provider = "openai"` 会让纯向量管线(父 Spec FV-03 的既有行为)和知识库摄入路径都用相同的 `model` 值构造 `OpenAIEmbeddingClient`。 |

## 7. 测试计划

### 7.1 单元测试——`InMemoryKnowledgeStore` Embedding 注入

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-015 | unit | `ingest_document()` 传入一个 fake `EmbeddingClient` 时,存储的是该 fake client 返回的向量作为 chunk 的 `embedding_vector`,而不是 `text_embedding()` 的输出(AC-FV03-009)。 |
| TC-FV03-016 | unit | `ingest_document()` 未传 `embedding_client`、构造函数也未设置时,对固定输入文本存储的 `embedding_vector` 值,和本 spec 之前的实现完全一致(AC-FV03-010,回归防护)。 |
| TC-FV03-017 | unit | `tests/test_knowledge_store.py` 中所有现有测试无需修改即可继续通过(FR-FV03-017)。 |

### 7.2 单元测试——运行时配置接线

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-018 | unit | `build_knowledge_store_embedding_client()` 在 `embedding_provider="openai"` 时返回一个用 `runtime_config.embedding_model` 配置好的 `OpenAIEmbeddingClient`(AC-FV03-012)。 |
| TC-FV03-019 | unit | `build_knowledge_store_embedding_client()` 在 `embedding_provider="mock"` 时返回 `None`。 |
| TC-FV03-020 | unit | `build_knowledge_store_embedding_client()` 遇到不支持的 provider 字符串时抛出 `ValueError`,与 `build_embedding_vector_rag_service_from_runtime_config()` 现有的错误处理惯例一致。 |

### 7.3 集成测试——编排器接线

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-021 | integration | 为一个 RAG 分类问题构造编排器的 fanout runner 时,得到的 `RagAgentRunner` 的 `vector_retriever is None`(AC-FV03-011)。 |
| TC-FV03-022 | integration | 对一个 RAG 分类问题发起 `POST /api/v2/chat/query`,在 `InMemoryKnowledgeStore.retrieve()` 上打桩(spy)后,记录到恰好一次 `retrieve()` 调用,且零次对任何 `VectorRagRetriever.retrieve()` 实现的调用。 |

## 8. 追踪矩阵

| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV03-014 | AC-FV03-009 | TC-FV03-015 |
| FR-FV03-015 | AC-FV03-012 | TC-FV03-018, TC-FV03-019, TC-FV03-020 |
| FR-FV03-016 | AC-FV03-011 | TC-FV03-021, TC-FV03-022 |
| FR-FV03-017 | AC-FV03-010 | TC-FV03-016, TC-FV03-017 |
| NFR-FV03-005 | AC-FV03-011 | TC-FV03-022 |
| NFR-FV03-006 | AC-FV03-010 | TC-FV03-016 |

## 9. 实现说明

- FR-FV03-014 里"`ingest_document()` 方法级参数优先于构造函数级"的设计(§5.1)是刻意的,不是疏漏:它允许同一个 `InMemoryKnowledgeStore` 实例,用真实 embedding client 摄入一部分文档、用确定性回退摄入另一部分(比如合成测试 fixture),而不需要构造两个独立的 store 实例。
- 本 spec 完全不动 `_rank_records()` 的融合公式——换上真实向量改变的是 `vector_score` 衡量的内容(真实语义相似度,而不是 token 哈希重叠),但 `0.60`/`0.35`/`source_score` 权重和排序管线的其余部分逐字节不变。本 spec 上线后如果出现明显的相关性排序变化,那是在提示*融合权重*可能需要重新调优(Spec FV03.4 的工作),而不是本 spec 本身有缺陷。
- `InMemoryVectorRagRetriever`/`_retrieve_vector_if_possible()` 刻意保留在代码库里,不删除,因为 `rag_v2.py`/`api/http.py` 会独立于主编排器的 `RagAgentRunner`,单独构造和使用它们来支撑一条独立的证据管线——删掉它们会是一次与本 spec 无关、范围更大的改动。
