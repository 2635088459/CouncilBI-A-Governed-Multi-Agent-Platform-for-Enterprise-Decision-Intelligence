# Spec FV03.3：加入真正的 Cross-Encoder 重排序阶段

来源设计：
- [4.3 加入真正的 Cross-Encoder 重排序阶段设计](../../../../system_design/final-version/zh-CN/04-followups/03-cross-encoder-reranking.zh-CN.md)
- [Spec FV03.1：统一"纯向量"与"混合检索"两条路径,并接入真实 Embedding](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.zh-CN.md) / [Spec FV03.2：用真正的 BM25 替换 Jaccard 式关键词重叠打分](02-bm25-keyword-scoring.spec.zh-CN.md)(本 spec 的重排序阶段作用在这两个 spec 已经产出的候选排序上,不改动它们)

---

## 1. 目的

`InMemoryKnowledgeStore.retrieve()` 自己的 docstring 已经声称是一个四阶段流程——`filter -> hybrid retrieval -> rerank -> dedupe -> evidence output`——但实际上不存在重排序阶段:今天在混合打分之后真正跑的,是对上一步刚算出来的同一批分数做去重和截断。本 spec 补上这个缺失的阶段:用一个 cross-encoder 模型,对收窄后的候选集合做真正的二次打分,联合读取 query 和 chunk,而不是事后比较各自独立算出来的分数。

## 2. 范围

**范围内：**
- 在混合打分(Spec FV03.1/FV03.2)和现有去重步骤之间插入一个重排序步骤,限定在 `retrieve()` 已经划出的收窄后 `2 * top_k` 候选窗口内。
- 一个本地运行的 cross-encoder 模型(`sentence-transformers` 的 `CrossEncoder` 包一层 `BAAI/bge-reranker-base`),每进程惰性加载一次。
- 用真实的经过 cross-encoder 的候选数量填充 `RetrievalStats.reranked_count`。
- 重排序模型不可用或报错时,回退到重排序前的混合排序。

**范围外：**
- 混合打分本身(Spec FV03.1/FV03.2)或 `_dedupe_adjacent_chunks()` 自身逻辑的任何改动。
- `RetrievalStats` schema 的任何改动——`reranked_count` 已经存在(父 Spec FV-03 的契约);本 spec 只改变填进去的值。
- 调用外部重排序 API/服务——模型跑在进程内,与 Spec FV03.1 的进程内 embedding 方案保持一致。

## 3. 功能需求

| ID | 需求 |
|---|---|
| FR-FV03-021 | `retrieve()` 必须在 `_dedupe_adjacent_chunks()` 和截断到 `top_k` 之前,用 cross-encoder 模型对混合打分排名前 `2 * top_k` 的候选重新打分,直接对 `(question, chunk_text)` 这一对打分。 |
| FR-FV03-022 | `RetrievalStats.reranked_count` 必须反映真正经过 cross-encoder 重排序的候选数量——配置了重排序器时为 `min(len(filtered_records), 2 * query.top_k)`,未配置时为 `0`。 |
| FR-FV03-023 | 若重排序模型加载失败,或在为某次请求的候选打分时抛出异常,`retrieve()` 必须回退到重排序前的混合排序,而不是让异常继续传播或让请求失败。 |

## 4. 非功能需求

| ID | 需求 |
|---|---|
| NFR-FV03-009 | cross-encoder 模型每个进程生命周期内最多加载一次(惰性单例或启动时加载),不得每次请求都重新加载。 |
| NFR-FV03-010 | 对 `2 * top_k` 规模的候选集合(默认 `top_k=5` 时为10对)做重排序,在 CPU 上给 P95 请求延迟增加的时间不得超过200ms,通过 `rag_benchmark.py` 现有的工具测量。 |

## 5. 数据契约

### 5.1 `CrossEncoderReranker` 与回退逻辑

```python
class CrossEncoderReranker(Protocol):
    def score(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]: ...


class BgeCrossEncoderReranker:
    """FR-FV03-021 / NFR-FV03-009：首次使用时惰性加载一次
    BAAI/bge-reranker-base——不是每次请求都加载。"""

    def __init__(self) -> None:
        self._model: "CrossEncoder | None" = None

    def score(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]:
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder("BAAI/bge-reranker-base")
        return tuple(float(s) for s in self._model.predict(list(pairs)))


def rerank(
    question: str,
    candidates: tuple[KnowledgeChunkRecord, ...],
    reranker: CrossEncoderReranker | None,
) -> tuple[KnowledgeChunkRecord, ...]:
    """FR-FV03-023：重排序器缺失或报错时,原样返回候选(重排序前的混合
    排序),而不是让异常继续传播。"""
    if reranker is None:
        return candidates
    try:
        pairs = tuple((question, c.chunk.chunk_text) for c in candidates)
        scores = reranker.score(pairs)
    except Exception:
        return candidates
    ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)
    return tuple(record for record, _ in ranked)
```

### 5.2 `retrieve()` 接入

```python
def retrieve(self, query: RetrievalQuery, trace_id: str = "") -> RetrievalResult:
    filtered_records = self.list_chunk_records(...)
    ranked_records = self._rank_records(filtered_records, query)          # Spec FV03.1/FV03.2
    narrowed = ranked_records[: max(query.top_k * 2, query.top_k)]
    reranked = rerank(query.question, narrowed, self._reranker)          # FR-FV03-021
    selected_records = self._dedupe_adjacent_chunks(reranked)
    selected_records = selected_records[: query.top_k]
    evidence_list = tuple(record.to_evidence_item() for record in selected_records)
    return RetrievalResult(
        evidence_list=evidence_list,
        ...,
        retrieval_stats=RetrievalStats(
            candidate_count=len(self._chunks_by_chunk_id),
            filtered_count=len(filtered_records),
            reranked_count=(
                min(len(filtered_records), query.top_k * 2)
                if self._reranker is not None
                else 0
            ),  # FR-FV03-022
            selected_count=len(evidence_list),
            latency_ms=latency_ms,
        ),
    )
```

## 6. 验收标准

| ID | 标准 |
|---|---|
| AC-FV03-017 | 对两个混合分数接近但只有一个真正回答了问题的候选(用一个 fake `CrossEncoderReranker` 验证),重排序后的顺序把真正相关的那个排在前面,即便它重排序前的混合分数更低。 |
| AC-FV03-018 | 配置了重排序器时,`RetrievalStats.reranked_count` 等于 `min(len(filtered_records), 2 * top_k)`;未配置时等于 `0`。 |
| AC-FV03-019 | 重排序器在打分时抛出异常时,`retrieve()` 仍然用重排序前的混合排序返回一个非错误结果,而不是让异常继续传播。 |
| AC-FV03-020 | 对同一个 `BgeCrossEncoderReranker` 实例连续发起 N 次 `retrieve()` 调用,cross-encoder 模型最多只被实例化一次。 |

## 7. 测试计划

### 7.1 单元测试——`rerank()`

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-031 | unit | `rerank()` 传入一个按反序打分的 fake 重排序器时,返回反序排列的候选(AC-FV03-017 的机制测试)。 |
| TC-FV03-032 | unit | `rerank()` 传入 `reranker=None` 时,原样返回候选,顺序不变。 |
| TC-FV03-033 | unit | `rerank()` 传入一个在 `score()` 上抛异常的 fake 重排序器时,原样返回候选(重排序前的顺序),而不是抛出异常(AC-FV03-019)。 |

### 7.2 单元测试——`BgeCrossEncoderReranker` 惰性加载

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-034 | unit | 对同一个 `BgeCrossEncoderReranker` 实例调用两次 `score()`,只触发一次模型构造(AC-FV03-020, NFR-FV03-009)。 |

### 7.3 单元测试——`retrieve()` 接入

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-035 | unit | `retrieve()` 配置了重排序器时,填充 `RetrievalStats.reranked_count == min(len(filtered_records), 2 * top_k)`(AC-FV03-018)。 |
| TC-FV03-036 | unit | `retrieve()` 未配置重排序器时,填充 `RetrievalStats.reranked_count == 0`。 |
| TC-FV03-037 | unit | `retrieve()` 配置了一个把某个特定 chunk 排最高的 fake 重排序器时,即使该 chunk 重排序前的混合分数低于另一个候选,`evidence_list` 里它依然排第一(AC-FV03-017)。 |

### 7.4 集成测试——真实模型

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-038 | integration | 配置了真实 `BgeCrossEncoderReranker` 时,对一个 RAG 分类问题发起 `POST /api/v2/chat/query` 成功完成,返回非空的 `evidence_list`,确认模型端到端正确加载并运行,而不仅仅是在单元测试里对着 fake 验证。 |

## 8. 追踪矩阵

| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV03-021 | AC-FV03-017 | TC-FV03-031, TC-FV03-037, TC-FV03-038 |
| FR-FV03-022 | AC-FV03-018 | TC-FV03-035, TC-FV03-036 |
| FR-FV03-023 | AC-FV03-019 | TC-FV03-032, TC-FV03-033 |
| NFR-FV03-009 | AC-FV03-020 | TC-FV03-034 |
| NFR-FV03-010 | — | (基准测试扩展,无专属测试用例；见 §9) |

## 9. 实现说明

- `rerank()`(§5.1)里的 `except Exception` 刻意写得很宽,不是一个更窄的异常类型——这和父 Spec FV-03 已经为"证据不足"建立的防御性降级姿态一致(FR-FV03-007 的"返回 warning 而不是编造事实"):重排序器的失败模式没法预先枚举完(模型加载失败、内存不足、输入格式异常),而回退行为(重排序前的排序)无论失败原因是什么都是安全的。
- TC-FV03-038 是本方案里唯一需要真正安装 `sentence-transformers`/`BAAI/bge-reranker-base` 依赖、且首次下载需要联网的测试——在没有这个依赖的 CI 环境里应该被标记跳过,这和项目里已经存在的、依赖真实 LLM 的 Docker 验证步骤(比如 Spec FV10.14 的真实模型验证)按环境可用性门控、而不是无条件运行的做法一致。
- NFR-FV03-010 的200ms预算相对于 CPU-only 的 `bge-reranker-base` 对10对短文本做一次前向推理来说是刻意留了余量的——实际耗时通常远低于这个数字,留出的空间是为了吸收 CI/本地硬件之间的差异,不是因为200ms被认为是真实下限。
