# Spec FV03.2：用真正的 BM25 替换 Jaccard 式关键词重叠打分

来源设计：
- [4.2 用真正的 BM25 替换 Jaccard 式关键词重叠打分设计](../../../../system_design/final-version/zh-CN/04-followups/02-bm25-keyword-scoring.zh-CN.md)
- [Spec FV03.1：统一"纯向量"与"混合检索"两条路径,并接入真实 Embedding](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.zh-CN.md)(本 spec 的 BM25 项通过不变的 `0.60`/`0.35` 权重,和 FV03.1 的真实 `vector_score` 融合)

---

## 1. 目的

`InMemoryKnowledgeStore._rank_records()` 的"关键词"分数只是一个普通的查询-token覆盖率比例(`len(query_set & chunk_set) / len(query_set)`),不是一个真正的词权重算法:没有词频加权、没有逆文档频率加权、没有文档长度归一化,而且它只认 ASCII 的分词器会静默丢弃所有中文 token。本 spec 用 BM25 替换它,在每次请求已经过权限过滤的候选集合上计算,同时修复中文分词的缺口。

## 2. 范围

**范围内：**
- 一个基于 BM25 的关键词打分器(`rank_bm25` 的 `BM25Okapi`),在每次请求时,针对 `list_chunk_records()` 已经过权限过滤的输出现建。
- 一个分词器扩展,在现有 ASCII 单词 token 之外,同时产出 CJK token。
- 在应用融合权重之前,把原始 BM25 分数做 min-max 归一化,归一化到与现有 `[0, 1]` 有界的 `cosine_similarity` 项可比的区间。

**范围外：**
- 向量/余弦打分的任何改动(Spec FV03.1)或重排序的任何改动(Spec FV03.3)。
- `0.60`/`0.35`/`source_score` 融合权重常量的任何改动。
- 持久化或预先构建的 BM25 索引——本 spec 的索引在每次请求时,针对已经过滤的候选集合现建(见 §9)。
- 任何外部搜索服务(ElasticSearch 或类似产品)——见 [4.5 用 pgvector 实现生产级向量检索设计](../../../../system_design/final-version/zh-CN/04-followups/05-pgvector-production-vector-search.zh-CN.md) §3,那里说明了为什么刻意不走这条路。

## 3. 功能需求

| ID | 需求 |
|---|---|
| FR-FV03-018 | 关键词打分必须使用 BM25(Okapi BM25 或等效的词频/逆文档频率/长度归一化公式),恰好在 `list_chunk_records()` 为当前请求返回的 `filtered_records` 候选集合上计算。不得在该权限过滤集合之外的任何文档上计算,也不得让全语料库的逆文档频率统计泄露该集合之外任何文档的信息。 |
| FR-FV03-019 | 用于 BM25 打分的关键词分词,必须把中文文本切分成可打分的单元(至少是 CJK 单字),不能只支持 ASCII 的 `[a-z0-9]+` token。 |
| FR-FV03-020 | 在应用 `0.60`/`0.35` 融合权重(与父 Spec FV-03 及 Spec FV03.1 保持不变)之前,一次请求的候选集合上的原始 BM25 分数必须被归一化(例如在该请求自己的候选集合内做 min-max 归一化),归一化到与现有 `[0, 1]` 有界的 `cosine_similarity` 项可比的区间。 |

## 4. 非功能需求

| ID | 需求 |
|---|---|
| NFR-FV03-007 | 对一次请求、最多1,000个 chunk 的权限过滤候选集合(与 `rag_benchmark.py` 的 `build_mock_rag_service` 默认语料规模一致)做 BM25 索引构建和打分,给每次请求检索延迟增加的 P95 时间不得超过 50ms。 |
| NFR-FV03-008 | 一个只含中文文本的 chunk,不得仅仅因为分词问题在关键词项上得分为 `0.0`——一个包含与查询相关的中文词的 chunk,针对一个共享该词的查询,必须产出非零的原始 BM25 分数。 |

## 5. 数据契约

### 5.1 分词器与 BM25 打分器

```python
def cjk_and_ascii_tokens(text: str) -> tuple[str, ...]:
    """FR-FV03-019：在现有的 ASCII 单词 token(与现有 text_tokens() 行为
    一致)之外,同时产出 CJK 单字 token,使中文 chunk/问题不会在关键词
    打分中被静默丢弃。"""
    ascii_tokens = re.findall(r"[a-z0-9]+", text.lower())
    cjk_tokens = re.findall(r"[一-鿿]", text)
    return tuple(ascii_tokens) + tuple(cjk_tokens)


def normalize_scores(raw_scores: tuple[float, ...]) -> tuple[float, ...]:
    """FR-FV03-020：min-max 归一化;全部相等的输入(包括只有一个候选的
    语料)映射为全零,而不是触发除零错误。"""
    if not raw_scores:
        return raw_scores
    lo, hi = min(raw_scores), max(raw_scores)
    if hi == lo:
        return tuple(0.0 for _ in raw_scores)
    return tuple((score - lo) / (hi - lo) for score in raw_scores)


class Bm25CandidateScorer:
    """FR-FV03-018：每次请求针对 filtered_records 现建——没有持久化/
    全局索引,不会跨请求或跨租户泄露统计信息。"""

    def __init__(self, filtered_records: tuple[KnowledgeChunkRecord, ...]) -> None:
        self._records = filtered_records
        corpus = [cjk_and_ascii_tokens(r.chunk.chunk_text) for r in filtered_records]
        self._bm25 = BM25Okapi(corpus)

    def scores(self, query_tokens: tuple[str, ...]) -> tuple[float, ...]:
        raw_scores = tuple(self._bm25.get_scores(list(query_tokens)))
        return normalize_scores(raw_scores)
```

### 5.2 `_rank_records` 接入

```python
def _rank_records(self, filtered_records, query):
    scorer = Bm25CandidateScorer(filtered_records)
    query_tokens = cjk_and_ascii_tokens(query.question)
    keyword_scores = scorer.scores(query_tokens)
    for record, keyword_score in zip(filtered_records, keyword_scores):
        vector_score = cosine_similarity(...)  # 不变，Spec FV03.1
        source_score = _source_weight(record.document.doc_type)
        relevance_score = round((keyword_score * 0.60) + (vector_score * 0.35) + source_score, 4)
        ...
```

## 6. 验收标准

| ID | 标准 |
|---|---|
| AC-FV03-013 | 对一个包含某个只在一个候选 chunk 中出现的稀有领域词的查询,该 chunk 的原始(归一化前)BM25 分数必须严格高于一个只匹配到等频但语料常见词的 chunk——回归验证 BM25 的 IDF 加权确实生效,不同于此前的 Jaccard 重叠,只要 token 集合交集大小相同,后者会给两个候选打出相同的分数。 |
| AC-FV03-014 | 一个只含中文文本的 chunk,和一个与它共享至少一个 CJK token 的中文问题,产出该 chunk 非零的原始 BM25 分数。 |
| AC-FV03-015 | 任何单次请求的候选集合上,归一化后的关键词分数都落在 `[0.0, 1.0]` 区间内。 |
| AC-FV03-016 | 每次 `retrieve()` 调用限定在不同的 `org_id`/权限上下文时,`_rank_records()` 的 BM25 索引都会重新构建——不会有来自先前、不同作用域请求的索引构成,影响当前请求的分数。 |

## 7. 测试计划

### 7.1 单元测试——BM25 打分器

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-023 | unit | `Bm25CandidateScorer.scores()` 对一个语料——其中一个 chunk 含稀有词、另一个只含常见词——针对包含该稀有词的查询,给稀有词 chunk 打出更高的原始分数(AC-FV03-013)。 |
| TC-FV03-024 | unit | `cjk_and_ascii_tokens()` 对一个中英混合字符串,同时返回 ASCII 单词 token 和单个 CJK 字符,ASCII 部分与现有的 ASCII 分词输出一致。 |
| TC-FV03-025 | unit | `normalize_scores()` 对全部相等的输入返回全零,而不是除零错误。 |
| TC-FV03-026 | unit | `normalize_scores()` 对一组原始分数,把最大值映射为 `1.0`、最小值映射为 `0.0`(AC-FV03-015)。 |

### 7.2 单元测试——`_rank_records` 接入

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-027 | unit | `_rank_records()` 对一个中文 chunk 和一个共享 CJK 词的中文问题,产出的 `relevance_score` 严格大于单独的 `source_score`,即 `keyword_score` 贡献了非零数值(AC-FV03-014)。 |
| TC-FV03-028 | unit | `_rank_records()` 每次调用都构造一个新的 `Bm25CandidateScorer`——通过断言两次使用不同 `filtered_records` 的调用,各自构建出独立的 BM25 语料来验证(AC-FV03-016)。 |

### 7.3 集成测试

| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-029 | integration | `InMemoryKnowledgeStore.retrieve()` 对一个匹配稀有领域词的查询,通过 `retrieve()` 现有的 filter → rank → dedupe 全流程,把含该词的 chunk 排在只匹配常见共享词的 chunk 之上。 |
| TC-FV03-030 | integration negative | 限定在 A 组织权限上下文的 `retrieve()`,对一个和 B 组织语料同类共享的 chunk,不论 B 组织下用同一个词的额外 chunk 有多少,返回的相关性分数都不变——验证不存在跨租户 IDF 泄露(AC-FV03-016)。 |

## 8. 追踪矩阵

| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV03-018 | AC-FV03-013, AC-FV03-016 | TC-FV03-023, TC-FV03-028, TC-FV03-029, TC-FV03-030 |
| FR-FV03-019 | AC-FV03-014 | TC-FV03-024, TC-FV03-027 |
| FR-FV03-020 | AC-FV03-015 | TC-FV03-025, TC-FV03-026 |
| NFR-FV03-007 | — | (基准测试扩展,无专属测试用例；见 §9) |
| NFR-FV03-008 | AC-FV03-014 | TC-FV03-027 |

## 9. 实现说明

- NFR-FV03-007 的延迟预算是通过扩展 `rag_benchmark.py` 现有的基准测试工具来验证的,而不是新增一个专属单元测试——这和父 Spec FV-03 自己的 `NFR-FV03-001` 只靠 `TC-FV03-008`(一个基准测试,不是单元测试)来验证的方式一致。
- `normalize_scores()` 的"全相等输入"分支(TC-FV03-025)在候选集合很小时(比如一个新入驻组织只有一个 chunk 的知识库)有实际意义——这种情况下 `BM25Okapi` 会退化为相同或近似相同的分数,如果不特殊处理,朴素的 min-max 归一化会触发除零。
- 中文分词刻意使用逐字符单字,而不是真正的分词器(比如 `jieba`):逐字符 n-gram 是 CJK 信息检索里一种站得住脚、不引入新依赖的基线方案,本 spec 不为了提升分词质量而引入新的运行时依赖。只有当类似 AC-FV03-014 的测试在实践中揭示出对分词敏感的误匹配问题时才需要重新考虑——那会是本 spec 的后续工作,不是本 spec 自身的缺口。
- FR-FV03-018"不做持久化索引"的决定(来源设计的 §2/§3 也有记录)意味着 BM25 统计量在每次 `retrieve()` 调用时都会重新计算。这是一个明确的取舍——用少量每次查询的 CPU 开销,换取"用户的 IDF 暴露范围永远恰好等于 `list_chunk_records()` 已经为他们过滤好的范围"这个保证——而不是承担一个陈旧或范围过宽的预建索引带来的正确性风险。Spec FV03.5(pgvector,不属于本 spec 集)是未来如果这个方案的持久化/性能问题被真实用量证实存在时,应该去解决它的地方。
