# Spec FV03.1–FV03.5：后续 Spec 索引

English version: [../../en/04-followups/README.en.md](../../en/04-followups/README.en.md)

这五份 spec 把 [04-followups 系统设计系列](../../../../system_design/final-version/zh-CN/04-followups/README.zh-CN.md) 转化成了可测试的需求,遵循本项目 SDD+TDD 的惯例:每一条功能需求(FR-)至少对应一条验收标准(AC-),每一条验收标准至少对应一条测试用例(TC-),每一条测试用例都能追溯回某条需求。需求编号延续父 [Spec FV-03:Embedding 与 Vector RAG](../03-embedding-vector-rag.spec.zh-CN.md) 自己的编号体系——`FR-FV03-014` 到 `FR-FV03-034`、`NFR-FV03-005` 到 `NFR-FV03-014`、`AC-FV03-009` 到 `AC-FV03-033`、`TC-FV03-015` 到 `TC-FV03-057`——直接接续该 spec 现有编号的最高值(`FR-FV03-013`、`NFR-FV03-004`、`AC-FV03-008`、`TC-FV03-014`),和 [10-followups spec 集合](../10-followups/README.zh-CN.md) 相对父 Spec FV-10 采用的惯例一致。

构建顺序是强制性的,不只是编号惯例——每一份 spec 都依赖前一份的产出:

1. [Spec FV03.1:统一"纯向量"与"混合检索"两条路径,并接入真实 Embedding](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.zh-CN.md) —— 必须最先构建。让混合打分路径(而不是纯向量路径)成为线上聊天查询唯一可达的路径,并给它接上真实的 `EmbeddingClient`。本套里其他每一份 spec 都假定这条路径已经是规范路径。**已实现。**
2. [Spec FV03.2:用真正的 BM25 替换 Jaccard 式关键词重叠打分](02-bm25-keyword-scoring.spec.zh-CN.md) —— 依赖 FV03.1(它要融合的 `vector_score` 项必须已经是真实的,否则单独升级关键词项到 BM25 无法被有意义地评估)。**已实现。**
3. [Spec FV03.3:加入真正的 Cross-Encoder 重排序阶段](03-cross-encoder-reranking.spec.zh-CN.md) —— 依赖 FV03.1/FV03.2 产出的候选排序;重排序作用在这两份 spec 已经排好的结果上,不改变它们的打分。**已实现**,并且用真实的 `BAAI/bge-reranker-base` 模型验证过,不只是靠 fake。
4. [Spec FV03.4:检索侧的标注数据集与 Hit Rate/MRR 自动化评估](04-golden-dataset-hit-rate-and-mrr-evaluation.spec.zh-CN.md) —— 依赖 FV03.1–FV03.3 产出一个稳定可评估的管线;如果针对 FV03.1 之前的管线运行,它测出来的 Hit Rate/MRR 数字描述的是一个这个平台已经不再运行的系统。**已实现**,标注了50道题的 Golden Dataset(它自己实现记录的 §9 提到,实际跑一遍检索后发现并纠正了一处标签问题,而不是盲信标注)。
5. [Spec FV03.5:用 pgvector 实现生产级向量检索](05-pgvector-production-vector-search.spec.zh-CN.md) —— 依赖 FV03.1–FV03.4 作为稳定基础;它自己来源设计的 §1 记录了一次只有在 FV03.1–FV03.4 落地之后才发现、做出的 schema 目标修正,这也是本 spec 被刻意排在最后、而不是提前投机性写好的原因。**已提出方案,尚未实现**——这是下一步。

## 状态

FV03.1–FV03.4 已经完整决策并实现,带有验收标准、测试计划和追踪矩阵。FV03.5 已经完整决策,但尚未实现。这五份都是在一次请求之后写就的:把 [04-followups 设计系列](../../../../system_design/final-version/zh-CN/04-followups/README.zh-CN.md) 转化成和 [10-followups spec 集合](../10-followups/README.zh-CN.md) 同等严谨程度的可测试需求,而不是继续停留在散文式的设计文档层面。每份 spec 自己的 §9 实现说明都记录了写作过程中做出的判断——例如 FV03.1 决定把 `InMemoryVectorRagRetriever` 留在代码库里而不删除(§9)、FV03.2 解释了为什么刻意拒绝一个持久化 BM25 索引、而选择一个限定在调用方自己权限过滤候选范围内、按请求现建的索引(§9)、FV03.3 说明了为什么它的异常处理刻意写得很宽(§9)、FV03.4 明确指出没有任何测试用例能替代人工为 Golden Dataset 的 ground truth 打对标签这件事(§9),以及 FV03.5 明确记录的两处刻意排除在范围之外的缺口(共享可见性的 SQL 支持,以及 pgvector 本身没有解决的"整个语料库仍在启动时一次性加载进内存"这道扩展性天花板——§9)。
