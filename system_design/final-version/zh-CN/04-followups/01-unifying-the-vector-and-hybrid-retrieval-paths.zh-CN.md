# 4.1 统一"纯向量"与"混合检索"两条路径,并接入真实 Embedding

## 1. 解决的问题

当前平台在 `RagAgentRunner` 背后其实并存**两条互不通信的检索机制**,而只有其中一条做了混合(关键词+向量)打分——另一条是纯向量检索。无论最终实际跑的是哪一条,"真实语义向量"和"混合打分"从来没有在同一条链路里同时发生过。本文档把两条路径合二为一,让 [第4章:Embedding、向量检索与 RAG](../04-embedding-vector-rag.zh-CN.md) 里已经设计好的混合打分公式,真正跑在生产环境的真实语义向量上,而不是一个占位实现上。

## 2. 现状梳理

`RagAgentRunner.run()`([src/chatbi/agents/rag_agent.py:62-82](../../../../src/chatbi/agents/rag_agent.py))按**固定优先级**尝试两种检索机制:

1. `_retrieve_vector_if_possible()`(62-82行内的84-114行)——只要设置了 `vector_retriever` 就优先跑这条。它调用 `InMemoryVectorRagRetriever.retrieve()`(176-207行),对问题做 embedding 后直接做纯 `VectorStore.search()`(余弦相似度)。**这条路径上完全没有关键词打分。**
2. `_retrieve_if_possible()`(116-137行)——只有第(1)步被跳过(即 `vector_retriever is None`)时才会跑。它调用 `InMemoryKnowledgeStore.retrieve()`([src/chatbi/knowledge.py:280-313](../../../../src/chatbi/knowledge.py)),这里**确实**计算了混合打分 `keyword_score * 0.60 + vector_score * 0.35 + source_score`([knowledge.py:356-362](../../../../src/chatbi/knowledge.py))。

问题在于:`InMemoryKnowledgeStore.ingest_document()`([knowledge.py:180-216](../../../../src/chatbi/knowledge.py))在生成每个 chunk 的存储向量时,硬编码调用本地的 `text_embedding()`——一个确定性的 token 哈希分桶伪 embedding(与 `embedding_vector_rag.py:584-591` 的 `_text_embedding` 是同一套手法),**不是**真实 embedding 模型。`InMemoryKnowledgeStore` 的构造函数和方法参数里,没有任何地方能注入一个 `EmbeddingClient`。与此同时,一个真实的 embedding provider 其实已经存在,只是接给了**另一条路径**:`OpenAIEmbeddingClient`([src/chatbi/embedding_vector_config.py:19-63](../../../../src/chatbi/embedding_vector_config.py))会真的调用 OpenAI embeddings API,通过 `runtime_config.embedding_provider == "openai"`([embedding_vector_config.py:74-81](../../../../src/chatbi/embedding_vector_config.py))选中——但这套接线只喂给了 `EmbeddingVectorRagService`/`InMemoryVectorRagRetriever`(路径1,纯向量那条),从没喂给 `InMemoryKnowledgeStore`(路径2,混合那条)。

净效果:不管某个 `RagAgentRunner` 实例实际走了哪条路径,至少有一个属性(真实语义,或者关键词感知打分)是缺失的。而且是**静默**缺失——不报错、不告警,`run()` 只是悄悄地根据 `vector_retriever is None` 走向其中一条分支。

## 3. 设计方案

**决定:废弃"纯向量路径"作为 `RagAgentRunner` 的主路径,让混合路径成为唯一的生产检索路径,并给它接上真实 embedding。**

1. **给 `InMemoryKnowledgeStore` 加一个可注入的 embedding client。** 在 `InMemoryKnowledgeStore.__init__` 和 `ingest_document(...)` 上增加 `embedding_client: EmbeddingClient | None = None` 参数。传入时,调用 `embedding_client.embed(EmbeddingRequest(input_texts=(text,)))` 并存储 `response.vectors[0]`,而不是调用本地的 `text_embedding()`;不传时,保持现有的确定性哈希分桶行为不变——这样 `tests/test_knowledge_store.py` 和 `tests/test_rag_agent.py` 里现有的所有测试都不用改就能继续通过,因为它们都没有传 `embedding_client`。
2. **把 `OpenAIEmbeddingClient` 接入知识库启动时的填充逻辑**,复用 `embedding_vector_config.py` 已经在读的 `runtime_config.embedding_provider` 开关——现在一个 embedding provider 配置项能同时控制两处调用点,而不是只控制一处。
3. **主编排器的 fanout 接线里,构造 `RagAgentRunner` 时不再传入非 `None` 的 `vector_retriever`。** `_retrieve_vector_if_possible()` 和 `InMemoryVectorRagRetriever` 不删除——如果 `rag_v2.py`/`api/http.py` 那条独立的证据管线有自己的理由要保持纯向量,可以继续用——但编排器构造 `RagAgentRunner` 时必须始终传 `vector_retriever=None`,让 `_retrieve_if_possible()`(混合路径)成为真正跑起来的那条。这一处改动才是真正堵住漏洞的地方:今天如果有人为了"加真实 embedding"而给编排器的 `RagAgentRunner` 接上 `vector_retriever`,实际效果是悄悄关掉了混合打分,而不是改进了它。
4. **本文档不改动 0.60/0.35/source_score 的融合权重。** 换上真实向量改变的是 `vector_score` 的"含义",不是公式本身;权重重新调优放到 [4.4 标注数据集与 Hit Rate/MRR 自动化评估](04-golden-dataset-hit-rate-and-mrr-evaluation.zh-CN.md),等有了标注数据集再去实测调整,而不是现在拍脑袋改。

## 4. 工作量评估

大约 **1.5–2 人天**:新增可选的构造/方法参数、接入真实 client 调用点,这部分改动小且机械;大部分时间花在梳理清楚当前所有构造 `InMemoryKnowledgeStore`/`RagAgentRunner` 的地方(编排器接线、各种 seed/demo 脚本、测试),逐一确认要不要改,而不是全局查找替换——因为有几个调用点**应该**继续保留确定性 mock(为了测试快、离线跑)。

## 5. 需求编号

| ID | 需求 | 状态 |
|---|---|---|
| FR-FV03-014 | `InMemoryKnowledgeStore` 必须支持可选注入 `EmbeddingClient`,传入时用它做 chunk embedding,未传入时回退到现有的确定性哈希分桶 embedding。 | 已实现 |
| FR-FV03-015 | 知识库的摄入路径必须读取纯向量管线已在读取的同一份 `runtime_config.embedding_provider`/`embedding_model` 配置,做到一个开关同时控制两处。 | 已实现 |
| FR-FV03-016 | 编排器构造 `RagAgentRunner` 时必须始终传 `vector_retriever=None`,确保线上聊天查询唯一可达的检索机制是混合打分路径。 | 已实现 |
| FR-FV03-017 | 本次改动不得让 `test_knowledge_store.py`/`test_rag_agent.py` 中任何现有测试回归——这些测试通过省略 `embedding_client` 继续走确定性 embedding 路径。 | 已实现 |
