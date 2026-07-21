# 4.3 加入真正的 Cross-Encoder 重排序阶段

## 1. 解决的问题

`InMemoryKnowledgeStore.retrieve()` 自己的 docstring 就已经声称是一个四阶段流程:`"""Run filter -> hybrid retrieval -> rerank -> dedupe -> evidence output."""`([src/chatbi/knowledge.py:281](../../../../src/chatbi/knowledge.py))。但实际上并不存在重排序阶段。代码在混合打分之后真正做的,是对**同一批**、在上一步刚计算出来的分数做去重和截断。本文档要补上这个缺失的阶段:用一个 cross-encoder 模型对一个收窄后的候选集合做真正的二次打分——不同于 [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md)/[4.2](02-bm25-keyword-scoring.zh-CN.md) 里那种各自独立打分、事后再比较的 bi-encoder/关键词分数,cross-encoder 会把 query 和 chunk 放在一起读。

## 2. 现状梳理

`retrieve()`([knowledge.py:280-313](../../../../src/chatbi/knowledge.py))目前的逻辑是:

```python
ranked_records = self._rank_records(filtered_records, query)                      # 混合打分
selected_records = self._dedupe_adjacent_chunks(ranked_records[: max(query.top_k * 2, query.top_k)])
selected_records = selected_records[: query.top_k]                                 # 截断
```

`_dedupe_adjacent_chunks` 只是去掉同一文档里相邻的近似重复 chunk;它不调用任何模型,也不重新计算任何分数。`RetrievalStats`([src/chatbi/core/contracts.py:149](../../../../src/chatbi/core/contracts.py))上已经存在的 `reranked_count` 字段,填的值是 `len(ranked_records)`([knowledge.py:308](../../../../src/chatbi/knowledge.py))——今天它的含义只是"有多少条记录算出了混合分数",而不是"有多少条真正经过了重排序"。这个字段已经接到了 API/遥测层,所以一旦真正的重排序存在,这里是上报它的天然位置,不需要新增字段。

## 3. 设计方案

1. **在混合打分和去重之间插入重排序步骤,只作用于收窄后的 2×`top_k` 候选窗口**——就是 `retrieve()` 在294行已经划出来的那个窗口,这样无论语料库多大,新增的开销都是有界的:重排序永远不会跑在超过 `2 * top_k` 个 chunk 上。
2. **模型选型:本地运行的 cross-encoder,不调用外部 API。** `sentence-transformers` 的 `CrossEncoder` 包一层 `BAAI/bge-reranker-base`,在这个候选集合规模下(每次查询几十对,不是几千对)CPU 就能跑,也和 [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md) 里进程内模型的设计保持一致,避免引入新的网络依赖及其在请求关键路径上自身的延迟/可用性故障模式。
3. **直接对 `(question, chunk_text)` 这一对打分**——这正是 cross-encoder 相对现有 bi-encoder 余弦分数的全部意义所在:它能联合关注 query 和 chunk,捕捉到独立计算的 embedding 会漏掉的相关性信号(否定、精确蕴含、条款级精确匹配)。
4. **按 cross-encoder 分数重新排序收窄后的候选集合,再照旧跑 `_dedupe_adjacent_chunks` 并截断到 `top_k`**——去重维持为纯后处理步骤,不改动。
5. **`reranked_count` 现在名副其实**:等于真正经过 cross-encoder 的候选数量,即 `min(len(filtered_records), 2 * query.top_k)`。不需要改动 API/契约——字段已经存在且已经对外暴露,只是填的值变得准确了。
6. **失败模式:** 如果重排序模型加载失败或某次请求报错,回退到重排序前的混合排序,而不是让整次检索失败——排序稍差的证据也严格好于没有证据,这和编排器里其他地方"降级而不是崩溃"的既有模式一致(参见 `PlanExecutor` 对非关键 agent 失败的处理,以及更广泛的 [07 弹性与扩展](../07-resilience-and-scale.zh-CN.md))。

## 4. 工作量评估

大约 **1.5–2 人天**:代码改动本身不大(新增一个步骤、输入规模有界、一个已存在字段只需填对值),但这个阶段是整个方案里唯一引入新运行时依赖的地方(本地模型下载/加载),而且需要测试回退路径,大部分时间花在这上面。

## 5. 需求编号

| ID | 需求 | 状态 |
|---|---|---|
| FR-FV03-021 | `retrieve()` 必须在去重和截断之前,用 cross-encoder 模型对混合打分排名前 `2 * top_k` 的候选重新打分。 | 待实现 |
| FR-FV03-022 | `RetrievalStats.reranked_count` 必须反映真正经过 cross-encoder 重排序的候选数量。 | 待实现 |
| FR-FV03-023 | 若重排序模型不可用或报错,检索必须回退到重排序前的混合排序,而不是让请求失败。 | 待实现 |
