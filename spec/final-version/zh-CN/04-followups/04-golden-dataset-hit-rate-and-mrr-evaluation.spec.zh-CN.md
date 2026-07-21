# Spec FV03.4：检索侧的标注数据集与 Hit Rate/MRR 自动化评估

来源设计：
- [4.4 检索侧的标注数据集与 Hit Rate/MRR 自动化评估设计](../../../../system_design/final-version/zh-CN/04-followups/04-golden-dataset-hit-rate-and-mrr-evaluation.zh-CN.md)
- [Spec FV03.1](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.zh-CN.md) / [Spec FV03.2](02-bm25-keyword-scoring.spec.zh-CN.md) / [Spec FV03.3](03-cross-encoder-reranking.spec.zh-CN.md)(本 spec 评估的正是这三个 spec 产出的检索管线;必须最后构建,否则它测出来的数字描述的是一个平台已经不再运行的系统)
- 本 spec 就地扩展 `EvaluationMetric`/`EvaluationScorer`(`src/chatbi/evaluation.py`)——final-version 没有单独的评估 spec 可以被取代;`evaluation.py` 现有行为只记录在代码里,以及 `spec/version1/10-evaluation-and-observability.spec.md`/`spec/version2/10-evaluation-and-observability.spec.md`,这两者都不属于本文档所在的 final-version spec 集合

---

## 1. 目的

目前这个平台用来做发布门禁的每一个指标,衡量的都是下游答案质量或延迟——从来没有单独衡量过检索质量本身。如果检索悄悄退化了,现有评估体系里没有任何东西一定能在它变成一个更模糊、更难诊断的 `rag_faithfulness` 下降之前抓出来。本 spec 给现有评估体系加上检索专属的 ground truth(`expected_chunk_ids`)和指标(Hit Rate@K、MRR),作为纯可观测性指标,接入和其他所有指标同一份报告。

## 2. 范围

**范围内：**
- `EvalCase` 上的 `expected_chunk_ids` 字段,以及 `evaluation_cases.py` 里对应的加载支持。
- 一份针对本项目 seed 数据里已有文档、标注了真实业务问题的 Golden Dataset,每题标注一个或多个预期 `chunk_id`。
- 一个新的 `retrieval_evaluation.py` 模块,针对真实检索管线(经过 Spec FV03.1–FV03.3 之后)计算 Hit Rate@3、Hit Rate@5 和 MRR。
- 两个新的 `EvaluationMetric` 成员(`RETRIEVAL_HIT_RATE`、`RETRIEVAL_MRR`),接入 `EvaluationScorer._metric_breakdown()` 现有的报告。

**范围外：**
- 新指标的任何发布门禁阈值——本 spec 不给 `ReleaseGatePolicy` 新增任何字段(见 FR-FV03-028/§9)。
- `rag_faithfulness`、`sql_accuracy` 或任何其他现有 `EvaluationMetric` 成员计算方式的任何改动。
- 人工标注这一步本身的自动化——它仍然是一个人工评审流程(§5.2),不是本 spec 产出的脚本。

## 3. 功能需求

| ID | 需求 |
|---|---|
| FR-FV03-024 | `EvalCase` 必须携带一个可选的 `expected_chunk_ids: tuple[str, ...] = ()` 字段。空元组的用例不得参与检索评分(和 `expected_sql_fragments` 已经用来决定一个用例是否参与 SQL 准确率评分的方式一致)。 |
| FR-FV03-025 | 必须存在一份至少50道真实业务问题的标注 Golden Dataset,每道题都对应本项目 seed 数据(`final_seed.py`)里已经存在的一份文档,每题标注一个或多个 `expected_chunk_ids`。 |
| FR-FV03-026 | 系统必须为 Golden Dataset 中的每一个用例计算 Hit Rate@3、Hit Rate@5 和平均倒数排名(MRR),必须针对真实的 `InMemoryKnowledgeStore.retrieve()` 管线(经过 Spec FV03.1–FV03.3 之后)运行,而不是 mock 或桩检索器。 |
| FR-FV03-027 | `EvaluationScorer._metric_breakdown()` 返回的映射,对任何包含 Golden Dataset 用例的评估运行,必须在平台现有六个 `EvaluationMetric` 值之外,包含 `retrieval_hit_rate` 和 `retrieval_mrr` 两个键。 |
| FR-FV03-028 | 本 spec 中,Hit Rate@K 和 MRR 不得影响 `ReleaseGatePolicy._release_gate_passed()` 的布尔结果——它们仅作可观测性用途。数值型发布门禁阈值明确推迟到未来某个有真实基线之后的 spec。 |

## 4. 非功能需求

| ID | 需求 |
|---|---|
| NFR-FV03-011 | Golden Dataset 里每一条 `expected_chunk_ids` 条目,在评估时都必须引用一个真实存在于本项目 seed 知识库里的 `chunk_id`——引用了不存在的 `chunk_id` 的数据集条目,必须让数据集校验失败,而不是静默地永远记为一次未命中。 |
| NFR-FV03-012 | 对约50道用例的 Golden Dataset 做一次完整的检索评估,必须在本地60秒内完成,使它能作为例行 CI 的一部分实际跑起来,而不是只能当成人工/离线任务。 |

## 5. 数据契约

### 5.1 Ground Truth:`EvalCase` 扩展

```python
@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    question: str
    expected_metric_id: str | None = None
    expected_sql_fragments: tuple[str, ...] = ()
    expected_chunk_ids: tuple[str, ...] = ()          # FR-FV03-024
    permission_context: Mapping[str, object] = field(default_factory=_empty_permission_context)
```

`evaluation_cases.py` 的 `_eval_case_from_mapping()` 增加对应的 `_string_tuple(raw_case, "expected_chunk_ids", index)` 调用,复用已经在给 `expected_sql_fragments` 使用的字符串元组加载/校验逻辑。

### 5.2 Golden Dataset

大约50对问题/`expected_chunk_ids`,构造方式:
- 复用 `tests/test_rag_agent.py`/`tests/test_knowledge_store.py` 里已经存在的问题作为种子集,这些测试本来就针对真实 seed 文档、且有已知正确的 chunk。
- 对于新问题:让 LLM *根据某个 chunk 的原文* 起草候选问题(这是从已知正确来源反推问题,不是生成答案),然后由人工评审确认或修改问题及其 `chunk_id` 标注后,才进入数据集——和本项目已经在 `src/chatbi/human_acceptance.py` 里记录的"人工确认 LLM 草稿"模式一致,不是本 spec 新引入的质控思路。

### 5.3 检索指标

```python
def hit_rate_at_k(
    retrieved_chunk_ids: tuple[str, ...],
    expected_chunk_ids: tuple[str, ...],
    k: int,
) -> bool:
    return bool(set(retrieved_chunk_ids[:k]) & set(expected_chunk_ids))


def reciprocal_rank(
    retrieved_chunk_ids: tuple[str, ...],
    expected_chunk_ids: tuple[str, ...],
) -> float:
    for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in expected_chunk_ids:
            return 1.0 / rank
    return 0.0


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationResult:
    case_id: str
    hit_at_3: bool
    hit_at_5: bool
    reciprocal_rank: float


class RetrievalEvaluator:
    def evaluate(
        self,
        cases: tuple[EvalCase, ...],
        retrieve_fn: Callable[[str], tuple[str, ...]],  # question -> 排序后的 chunk_ids
    ) -> tuple[RetrievalEvaluationResult, ...]:
        results: list[RetrievalEvaluationResult] = []
        for case in cases:
            if not case.expected_chunk_ids:
                continue
            retrieved = retrieve_fn(case.question)
            results.append(RetrievalEvaluationResult(
                case_id=case.case_id,
                hit_at_3=hit_rate_at_k(retrieved, case.expected_chunk_ids, 3),
                hit_at_5=hit_rate_at_k(retrieved, case.expected_chunk_ids, 5),
                reciprocal_rank=reciprocal_rank(retrieved, case.expected_chunk_ids),
            ))
        return tuple(results)

    def aggregate(self, results: tuple[RetrievalEvaluationResult, ...]) -> Mapping[str, float]:
        if not results:
            return {"retrieval_hit_rate": 1.0, "retrieval_hit_rate_at_5": 1.0, "retrieval_mrr": 1.0}
        return {
            "retrieval_hit_rate": sum(r.hit_at_3 for r in results) / len(results),
            "retrieval_hit_rate_at_5": sum(r.hit_at_5 for r in results) / len(results),
            "retrieval_mrr": sum(r.reciprocal_rank for r in results) / len(results),
        }
```

### 5.4 `EvaluationMetric` 与 Scorer 扩展

```python
class EvaluationMetric(StrEnum):
    SQL_ACCURACY = "sql_accuracy"
    SQL_SAFETY = "sql_safety"
    AGENT_ROUTING = "agent_routing"
    RAG_FAITHFULNESS = "rag_faithfulness"
    LATENCY_P95 = "latency_p95"
    UNSUPPORTED_CLAIM_RATE = "unsupported_claim_rate"
    RETRIEVAL_HIT_RATE = "retrieval_hit_rate"      # FR-FV03-027
    RETRIEVAL_MRR = "retrieval_mrr"                # FR-FV03-027
```

`EvaluationScorer._metric_breakdown()` 新增这两个键,由一次 `RetrievalEvaluator.aggregate()` 调用填充,与现有的 `observations`/`expectations` 参数并列传入。本 spec **不**修改 `ReleaseGatePolicy` 和 `_release_gate_passed()`(FR-FV03-028)。

## 6. 验收标准

| ID | 标准 |
|---|---|
| AC-FV03-021 | 加载一个带 `expected_chunk_ids` 数组的评估用例映射,能正确填充 `EvalCase.expected_chunk_ids`;省略该字段时默认为 `()`。 |
| AC-FV03-022 | Golden Dataset 中至少有50条 `expected_chunk_ids` 非空的用例,每条都引用一个真实存在于本项目 seed 知识库里的 `chunk_id`(NFR-FV03-011)。 |
| AC-FV03-023 | 针对真实的 `InMemoryKnowledgeStore.retrieve()` 管线运行 `RetrievalEvaluator.evaluate()`,为每一个 `expected_chunk_ids` 非空的用例都产出一条结果。 |
| AC-FV03-024 | 对任何包含 Golden Dataset 用例的评估运行,`EvaluationScorer._metric_breakdown()` 返回的映射,在现有六个指标之外,包含 `retrieval_hit_rate` 和 `retrieval_mrr` 键。 |
| AC-FV03-025 | `EvaluationScorer._release_gate_passed()` 的布尔结果不受 `retrieval_hit_rate`/`retrieval_mrr` 数值影响——一次 `retrieval_hit_rate == 0.0` 的运行,只要其他现有门禁条件都满足,依然能通过发布门禁。 |
| AC-FV03-026 | 对一个未发生变化的知识库和检索管线,连续运行两次检索评估套件,每个用例的 `hit_at_3`/`hit_at_5`/`reciprocal_rank` 数值都完全一致(确定性检查)。 |

## 7. 测试计划

### 7.1 单元测试——Ground Truth 与指标函数

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-039 | unit | 加载一个带 `expected_chunk_ids` 的 `EvalCase` 映射能正确填充该字段(AC-FV03-021)。 |
| TC-FV03-040 | unit | 加载一个不带 `expected_chunk_ids` 的 `EvalCase` 映射,该字段默认为 `()`(AC-FV03-021)。 |
| TC-FV03-041 | unit | `hit_rate_at_k()` 在任意一个预期 chunk id 出现在前 `k` 个检索结果中时返回 `True`,否则返回 `False`。 |
| TC-FV03-042 | unit | `reciprocal_rank()` 对第一个匹配 chunk id 的1-索引位置返回 `1/rank`,检索结果中不存在任何预期 chunk id 时返回 `0.0`。 |

### 7.2 单元测试——`RetrievalEvaluator`

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-043 | unit | `RetrievalEvaluator.evaluate()` 跳过 `expected_chunk_ids` 为空的用例——不会为它们调用 `retrieve_fn`。 |
| TC-FV03-044 | unit | `RetrievalEvaluator.aggregate()` 对一组固定的 `RetrievalEvaluationResult`,把 `retrieval_hit_rate`/`retrieval_hit_rate_at_5`/`retrieval_mrr` 算成各用例值的算术平均。 |

### 7.3 集成测试——评估流水线

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-045 | integration | 针对真实 `InMemoryKnowledgeStore.retrieve()` 管线,对 Golden Dataset 运行 `RetrievalEvaluator.evaluate()`,为每一个 `expected_chunk_ids` 非空的用例都产出结果;如果任何 `expected_chunk_ids` 条目引用了 seed 库中不存在的 `chunk_id`,在 fixture 加载阶段就失败(AC-FV03-022, AC-FV03-023)。 |
| TC-FV03-046 | integration | 对一个包含 Golden Dataset 用例的评估套件运行 `EvaluationScorer.score_suite()`,返回的 `metric_breakdown` 包含 `retrieval_hit_rate` 和 `retrieval_mrr`(AC-FV03-024)。 |
| TC-FV03-047 | integration negative | 一次 `retrieval_hit_rate == 0.0` 但其他现有门禁条件都满足的运行,`EvaluationScorer._release_gate_passed()` 返回 `True`(AC-FV03-025;验证 FR-FV03-028 的纯可观测性状态)。 |
| TC-FV03-048 | integration | 针对同一个 seed 知识库,连续两次运行检索评估套件,两次得到的聚合指标完全一致(AC-FV03-026)。 |

## 8. 追踪矩阵

| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV03-024 | AC-FV03-021 | TC-FV03-039, TC-FV03-040 |
| FR-FV03-025 | AC-FV03-022 | TC-FV03-045 |
| FR-FV03-026 | AC-FV03-023 | TC-FV03-041, TC-FV03-042, TC-FV03-043, TC-FV03-045 |
| FR-FV03-027 | AC-FV03-024 | TC-FV03-044, TC-FV03-046 |
| FR-FV03-028 | AC-FV03-025 | TC-FV03-047 |
| NFR-FV03-011 | AC-FV03-022 | TC-FV03-045 |
| NFR-FV03-012 | — | (通过 CI 任务耗时衡量,无专属测试用例；见 §9) |

## 9. 实现说明

- FR-FV03-025(Golden Dataset 的存在)没有代码需求那种意义上的专属"单元测试"——它的验收标准(AC-FV03-022)是一个数据质量断言,由同一个 fixture 加载测试(TC-FV03-045)检查:任何 `expected_chunk_ids` 条目引用了当前 seed 中不存在的 `chunk_id`,该测试就失败(NFR-FV03-011)。这和 Spec FV10.11 对待 fixture 数据正确性的方式一致——靠拿它跑一遍真实代码来验证,而不是写一个只验证手工挑选值的测试。
- AC-FV03-025/TC-FV03-047 是这样一个测试:如果以后有人在没有专门的后续 spec 决定要这么做的情况下,就给 `ReleaseGatePolicy` 加了一个带非零默认值的 `min_retrieval_hit_rate` 字段,这个测试就会抓到这个回归——本 spec 的意图是现在完全不存在这样一个字段(FR-FV03-028),这个测试把这条边界显式地强制住,而不是指望评审人靠肉眼发现。
- AC-FV03-022 背后大约50道问题的标注工作量,超出了本 spec 可自动化的测试范围:TC-FV03-045 验证的是数据集的*结构*完整性(每个引用的 `chunk_id` 都存在),但没法验证人工是否为某道题标注了*正确*的 `chunk_id`——那是 §5.2 已经描述过的人工评审判断,不是一个测试用例能替代的。
- 本 spec 必须在 Spec FV03.1–FV03.3 都落地之后才能构建和评估——如果针对 FV03.1 之前的管线(假哈希分桶 embedding、Jaccard 关键词重叠、无重排序)运行,测出来的 Hit Rate/MRR 数字描述的是一个这个平台已经不再运行的检索管线,一旦 FV03.1–FV03.3 上线,任何由此得到的基线就立刻失去意义。
