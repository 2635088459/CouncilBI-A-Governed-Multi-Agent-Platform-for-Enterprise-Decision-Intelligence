# 4.4 检索侧的标注数据集与 Hit Rate/MRR 自动化评估

## 1. 解决的问题

目前平台用来决定能否发布的每一个指标,衡量的都是**下游**答案质量——从来没有单独衡量过检索质量本身。如果检索悄悄退化了(重排序模型上线出问题、语料库重新摄入时丢了一份文档、分词器改动),现有评估体系里没有任何东西一定能在它变成一个更模糊、更难诊断的 `rag_faithfulness` 下降之前把它抓出来。本文档给检索单独加上 ground truth 和指标——Hit Rate@K 和 MRR——把它作为同一套评估体系里的一等公民、自动化的一部分,而不是一次性脚本。

## 2. 现状梳理

- `EvaluationMetric`([src/chatbi/evaluation.py:18-24](../../../../src/chatbi/evaluation.py))有六个成员——`SQL_ACCURACY`、`SQL_SAFETY`、`AGENT_ROUTING`、`RAG_FAITHFULNESS`、`LATENCY_P95`、`UNSUPPORTED_CLAIM_RATE`——没有一个是检索专属的。`RAG_FAITHFULNESS`([evaluation.py:217-227](../../../../src/chatbi/evaluation.py))衡量的是"答案里的论断是否被**检索恰好返回的**证据支撑",完全不涉及检索有没有一开始就找对证据。
- `EvalCase`([src/chatbi/evaluation_repository.py:44-58](../../../../src/chatbi/evaluation_repository.py))为 SQL 准确率评分带了 `expected_sql_fragments` 字段,但没有对应的"这个问题应该检索到哪些 chunk"字段。
- `rag_benchmark.py:19-105` 只测延迟(`p95_latency_ms`、`meets_local_p95_target`);它自己的模块 docstring 就写着"This module is not a production metrics system"([rag_benchmark.py:1-3](../../../../src/chatbi/rag_benchmark.py)),而且跑在 `build_mock_rag_service` 生成的约1000条合成 chunk 语料上,不是真实 seed 内容。
- 在 `evaluation*.py` 全仓搜索,没有任何地方出现"hit_rate"、"recall"、"precision"或"mrr"——这是全新内容,不是对现有指标的改名或扩展。

## 3. 设计方案

### 3.1 Ground Truth:扩展 `EvalCase`

新增一个字段:

```python
expected_chunk_ids: tuple[str, ...] = ()
```

和现有的 `expected_sql_fragments` 并列放在 `EvalCase`([evaluation_repository.py:44-58](../../../../src/chatbi/evaluation_repository.py))上,并在 `evaluation_cases.py:25-35` 对应的 loader 里加上加载逻辑。空元组的用例就是不参与检索评分(和 `expected_sql_fragments` 今天用来决定一个用例是否参与 SQL 准确率评分的方式一致)。

### 3.2 标注数据集

针对本项目自身 seed 数据(`final_seed.py`)里已经存在的文档,构造大约 **50 道真实业务问题**,每道题标注上"正确检索应该命中的 `chunk_id`"。这是一个**人工标注任务**,不适合脚本化——这也是整个四阶段方案里耗时最长的单项工作。有两个办法能让它不必从零开始:
- 复用 `tests/test_rag_agent.py`/`tests/test_knowledge_store.py` 里已经存在的问题作为种子集,因为这些测试已经针对真实 seed 文档、且已知正确 chunk。
- 对真正的新问题,可以让 LLM **根据某个 chunk 的原文反推问题**(生成问题比回答问题精度容易保证得多),然后由人工确认/修改每一条问题及其 `chunk_id` 标注——这和项目已有的"人工确认 LLM 草稿"模式(`src/chatbi/human_acceptance.py`)是同一套质控思路,不是给这个代码库新引入一种质量把关哲学。

### 3.3 指标计算

新增模块 `retrieval_evaluation.py`,与 `evaluation.py` 平行、不合并进去(检索评估需要每道题的原始排序 chunk_id 列表,和 `EvaluationObservation` 面向答案级别的字段形状不同):

```python
def hit_rate_at_k(retrieved_chunk_ids: tuple[str, ...], expected_chunk_ids: tuple[str, ...], k: int) -> bool:
    return bool(set(retrieved_chunk_ids[:k]) & set(expected_chunk_ids))

def reciprocal_rank(retrieved_chunk_ids: tuple[str, ...], expected_chunk_ids: tuple[str, ...]) -> float:
    for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in expected_chunk_ids:
            return 1.0 / rank
    return 0.0
```

`RetrievalEvaluator.evaluate(cases, retrieve_fn)` 让每道题都跑一遍真实的 `InMemoryKnowledgeStore.retrieve()`(经过 [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md)/[4.2](02-bm25-keyword-scoring.zh-CN.md)/[4.3](03-cross-encoder-reranking.zh-CN.md) 之后的真实管线,不是 mock),并在整个数据集上聚合 `hit_rate@3`、`hit_rate@5` 和 `mrr`——这和本方案最初参照的那份面试 PPT 例子用的 K 值一致,方便最终的前后对比数字能直接和那个说法对上。

### 3.4 接入发布门禁

在枚举里新增 `EvaluationMetric.RETRIEVAL_HIT_RATE` 和 `EvaluationMetric.RETRIEVAL_MRR`,并加进 `EvaluationScorer._metric_breakdown()` 返回的映射里([evaluation.py:141-167](../../../../src/chatbi/evaluation.py)),让检索质量出现在和其他所有指标同一份评估报告里,而不是一个没人看的独立看板。

**决定:** 这两个指标一开始只做**可观测性用途,不做发布门禁**——本阶段不给 `ReleaseGatePolicy`([evaluation.py:60-70](../../../../src/chatbi/evaluation.py))新增阈值。在还没有"正常水平"基线的情况下就拿一个指标做门禁,有可能因为噪声而挡住正常发布。等真实跑了几轮评估、建立起稳定基线之后,后续可以像今天 `max_unsupported_claim_rate` 那样,加一个 `min_retrieval_hit_rate` 阈值。

## 4. 工作量评估

大约 **2.5–3.5 人天**,而且这个阶段的成本主要在人工标注时间,不是工程量:`EvalCase` 字段新增、新指标模块、发布门禁接线,每一项都不到半天;手工标注约50道问题/chunk_id 对(即便借助已有测试用例和 LLM 草稿起步)要认真做对,现实中需要一天以上的仔细人工核查,因为一个标错的标签会悄悄污染下游所有 Hit Rate/MRR 数字。

## 5. 需求编号

| ID | 需求 | 状态 |
|---|---|---|
| FR-FV03-024 | `EvalCase` 必须携带可选的 `expected_chunk_ids` 字段,作为检索的 ground truth。 | 待实现 |
| FR-FV03-025 | 必须存在一份针对真实 seed 文档、标注了真实业务问题的 Golden Dataset,每题标注一个或多个预期 chunk ID。 | 待实现 |
| FR-FV03-026 | 系统必须在真实检索管线(而非 mock)上,针对 Golden Dataset 计算 Hit Rate@K 和 MRR。 | 待实现 |
| FR-FV03-027 | Hit Rate@K 和 MRR 必须出现在和平台其他评估指标同一份 `metric_breakdown` 报告里。 | 待实现 |
| FR-FV03-028 | Hit Rate@K 和 MRR 初期仅作为可观测性指标;发布门禁的数值阈值推迟到有真实基线之后再定。 | 待实现 |
