# Spec FV10.12:混合文件/数仓对比回答的证据相关性过滤与 Join 不匹配提示

English version: [../../en/10-followups/12-evidence-relevance-and-join-mismatch-caveats.spec.en.md](../../en/10-followups/12-evidence-relevance-and-join-mismatch-caveats.spec.en.md)

来源设计文档:
- [10.12 混合文件/数仓对比回答的证据相关性过滤与 Join 不匹配提示](../../../../system_design/final-version/zh-CN/10-followups/12-evidence-relevance-and-join-mismatch-caveats.zh-CN.md)
- [Spec FV-10: 用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)(父 Spec;本 Spec 修订 `_handle_file_data_chat_query()` 的证据处理逻辑和 `FederatedQueryAgent` 的输出契约)

本 Spec 按本项目一贯的 SDD+TDD 顺序,**先写 Spec、再实现**——这跟 [Spec FV10.6](06-hybrid-file-answering-for-mixed-selections.spec.zh-CN.md)、[Spec FV10.10](10-per-file-relevance-filtering-in-mixed-selections.spec.zh-CN.md)、[Spec FV10.11](11-value-sample-aware-schema-context.spec.zh-CN.md) 采用的顺序一致——跟 Spec FV10.5 或 Spec FV10.9 那种"先靠实盘复现把修复做完、再补写 Spec"的顺序不同。下面每一条功能需求都至少对应一条验收标准和一条测试用例;每一条测试用例都能追溯回一条需求。测试用例先针对实现之前的代码确认跑出了**红灯**,实现完成之后再确认跑出**绿灯**——第 10 节记录了在写 TC-FV10-198 的测试数据、还没有真正拿去跑之前,第 6.1 节的相关性下限就被发现需要修正的经过。

---

## 1. 目的

一次真实的回答暴露出混合文件/数仓对比路径(`src/chatbi/api/http.py` 里的 `_handle_file_data_chat_query()`)存在两个相互独立的结构性缺陷:

1. 从全组织知识库检索出来的证据,不管有没有达到任何有意义的相关性门槛,都会被当成答案的"来源"渲染出来——因为 `InMemoryKnowledgeStore.retrieve()` 唯一的下限是 `relevance_score > 0`,而 `ResultMerger._tag_evidence()` 会原样拼接传给它的任何内容,自己完全没有阈值。
2. 一次 `FederatedQueryAgent` 对比查询,如果因为 `JOIN` 条件根本没匹配上任何东西而返回 0 行,跟一次真的没有行超过阈值的对比查询,会被叙述成完全一样的结果——`FederatedQueryAgentOutput` 里没有任何字段能区分"没匹配上"和"匹配上了、而且通过了"。

本 Spec 新增:(a) 在知识库证据被渲染出来的那一刻,加一道相关性分数下限,范围只限定在混合文件路径;(b) 在 `FederatedQueryAgentOutput` 上新增一个 `zero_row_join_caveat` 信号,当一条包含 `JOIN` 的查询在数据源视图非空的情况下返回 0 行时,把这个信号传给答案合成 prompt。

## 2. 范围

**范围内:**
- 在 `_handle_file_data_chat_query()`(`src/chatbi/api/http.py`)内部,紧接着从 `retrieval_result.evidence_list` 构造出 `EvidenceItem` 之后,新增一个模块级常量和过滤逻辑,应用在 `knowledge_base_evidence` 上。
- 在 `FederatedQueryAgentOutput`(`src/chatbi/files/contracts.py`)上新增 `zero_row_join_caveat: bool` 字段,由 `FederatedQueryAgent.run()`(`src/chatbi/agents/federated_query_agent.py`)内部计算。
- 当 `zero_row_join_caveat` 为 `True` 时,给答案合成 prompt 传入一条明确指令。

**范围外:**
- 不改动 `QuestionClassifier._RAG_KEYWORDS` 或 `classify()`——本 Spec 不改变知识库检索**何时**被触发,只改变检索结果**如何被使用**。具体原因见来源设计文档第 6 节。
- 不改动 `InMemoryKnowledgeStore.retrieve()` 自身的排序逻辑或它的 `relevance_score <= 0` 下限(`src/chatbi/knowledge.py:363`)——本 Spec 新增的下限是由调用方施加的,不是知识库内部的改动。
- 不检测*局部* join 不匹配(部分行匹配上了、部分悄悄漏掉了)——`zero_row_join_caveat` 只会在结果完全为空时触发,详见来源设计文档第 6 节。
- 不改动 `uploaded_file_evidence`/`FileScopedRetriever` 自身的相关性逻辑,这部分已经由 [Spec FV10.6](06-hybrid-file-answering-for-mixed-selections.spec.zh-CN.md) 规定。
- 不改动主编排器(非文件路径)自己的 RAG 证据流程。

## 3. 参与者

复用父 Spec FV-10 第 3 节定义的参与者,不新增参与者。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-084 | 在 `_handle_file_data_chat_query()` 内部,由 `active_knowledge_store.retrieve()` 结果构造出的 `EvidenceItem`,如果其 `relevance_score` 低于一个固定的最低下限(`_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE`),必须被排除在 `knowledge_base_evidence` 之外。 |
| FR-FV10-085 | `FederatedQueryAgentOutput` 必须暴露一个 `zero_row_join_caveat: bool` 字段(默认 `False`),由 `FederatedQueryAgent.run()` 在以下条件同时成立时设为 `True`:(a) 最终查询结果为 0 行;(b) 生成的 SQL 文本包含大小写不敏感的子串 `join`;(c) 已物化的 Postgres 视图和每一个已物化的文件视图,在查询执行前都至少有一行数据。 |
| FR-FV10-086 | 当 `FederatedQueryAgentOutput.zero_row_join_caveat` 为 `True` 时,`_handle_file_data_chat_query()` 必须在答案合成请求中包含一条明确指令,说明在 join key 上没有找到匹配的记录,并且这个结果不得被表述为确认了任何阈值或对比结论。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-029 | FR-FV10-084 的相关性下限只能应用在 `_handle_file_data_chat_query()` 内部计算出的 `knowledge_base_evidence` 上。不得应用到 `uploaded_file_evidence`(来自 `FileScopedRetriever`),也不得改变主编排器(非文件路径)计算出的任何 RAG 证据。 |

## 6. 数据契约

### 6.1 相关性下限 — `src/chatbi/api/http.py`

```python
_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE = 0.15  # 实现过程中修正过——见第 10 节

knowledge_base_evidence = tuple(
    EvidenceItem(
        source_id=item.source_id,
        title=item.title,
        citation_anchor=item.citation_anchor,
        snippet=item.snippet,
        relevance_score=item.relevance_score,
    )
    for item in retrieval_result.evidence_list
    if item.relevance_score >= _MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE
)
```

`0.15` 是本 Spec 最终定下的固定值——从最初提议的 `0.35` 修正而来,因为实现过程中发现更高的那个值会丢掉一条既有回归测试已经断言应该被返回的证据(见第 10 节)。它高于 `InMemoryKnowledgeStore` 那道 `> 0` 的综合分数下限(`knowledge.py:363`),同时能放行那份真正切题的文档;TC-FV10-198 会固定用来验证这个数值的具体 fixture 分数。`uploaded_file_evidence` 是由另一条独立的代码路径(`file_scoped_retriever.retrieve(...)`,不变)构造的,不经过这道过滤。

### 6.2 `FederatedQueryAgentOutput` — `src/chatbi/files/contracts.py`

```python
@dataclass(frozen=True, slots=True)
class FederatedQueryAgentOutput:
    degraded: bool
    table_result: TableResult | None = None
    federated_sql: str | None = None
    error_code: str | None = None
    degradation_reason: str | None = None
    zero_row_join_caveat: bool = False
```

### 6.3 `FederatedQueryAgent.run()` — `src/chatbi/agents/federated_query_agent.py`

```python
try:
    columns, rows = fetch_table(connection, sql_text)
except QueryResourceExceededError:
    return FederatedQueryAgentOutput(
        degraded=False, error_code="QUERY_RESOURCE_EXCEEDED", federated_sql=sql_text,
    )
except InvalidGeneratedSqlError:
    return FederatedQueryAgentOutput(
        degraded=False, error_code="INVALID_GENERATED_SQL", federated_sql=sql_text,
    )

zero_row_join_caveat = (
    not rows
    and "join" in sql_text.lower()
    and self._source_row_count(connection, request.pg_context.table_name) > 0
    and all(
        self._source_row_count(connection, f"file_{file.id}") > 0
        for file in structured_files
    )
)
return FederatedQueryAgentOutput(
    degraded=False,
    table_result=TableResult(columns=columns, rows=rows),
    federated_sql=sql_text,
    zero_row_join_caveat=zero_row_join_caveat,
)
```

`_source_row_count()` 是一个新增的私有辅助方法,对已经打开的 DuckDB 连接发出 `SELECT COUNT(*) FROM "<view_name>"`——`db_{table}` 和每一个 `file_{file_id}` 视图在这个时间点都已经由 `_register_views()`(不变)物化完毕,所以这里只是新增两次轻量级的内存内 `COUNT(*)` 查询,不是引入新的数据源。

### 6.4 答案合成指令 — `src/chatbi/api/http.py`

```python
if federated_output is not None and federated_output.zero_row_join_caveat:
    synthesis_instructions += (
        "\n\nThe comparison query matched zero rows across the join, even though "
        "both the file and the warehouse table each had data for this period. "
        "State plainly that no matching records were found across the join "
        "key(s) — do not claim this means all values are within any threshold, "
        "since a join-key mismatch (e.g. differing spelling, capitalization, or "
        "date format between the file and the warehouse column) produces the "
        "identical zero-row result. Recommend the user verify that the shared "
        "column(s) use the same values/format in both sources."
    )
```

具体以什么机制把这段内容附加到答案合成请求里(是拼进 prompt 字符串,还是作为合成器输入上的一个结构化字段)属于实现细节,留给 `answer_synthesis.py` 现有的接口决定;本 Spec 的需求(FR-FV10-086)只要求:只要这个标志位为 `True`,这条指令就必须传到合成器手上,并且措辞上要能阻止它得出"没有差异"这种结论。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-089 | 给定 `retrieval_result.evidence_list` 的 `relevance_score` 分别为 `[0.9, 0.4, 0.1]`,固定下限为 `_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE`,`knowledge_base_evidence` 应当恰好包含 `0.9` 和 `0.4` 这两项;`0.1` 那一项应被排除。 |
| AC-FV10-090 | 使用跟 AC-FV10-089 相同的测试数据,`uploaded_file_evidence`(独立构造)在数量和内容上都不受影响——这道下限对它没有任何效果。 |
| AC-FV10-091 | 给定一次 `FederatedQueryAgent.run()` 调用:生成的 SQL 包含 `JOIN`,Postgres 侧视图有 3 行,文件侧视图有 5 行,实际执行的查询返回 0 行,返回的 `FederatedQueryAgentOutput.zero_row_join_caveat` 应为 `True`。 |
| AC-FV10-092 | 使用跟 AC-FV10-091 相同的测试数据,但 join key 确实能匹配上、产出非空结果时,`zero_row_join_caveat` 应为 `False`。 |
| AC-FV10-093 | 给定一份文件侧视图为 0 行(一份空的上传文件)、查询返回 0 行的测试数据,`zero_row_join_caveat` 应为 `False`——空结果是因为数据源本身为空,不是 join 不匹配。 |
| AC-FV10-094 | 当 `_handle_file_data_chat_query()` 处理一个 `zero_row_join_caveat=True` 的 `FederatedQueryAgentOutput` 时,传给答案合成器的请求应包含第 6.4 节的 join 不匹配指令文本;当 `zero_row_join_caveat=False` 时,不应包含。 |
| AC-FV10-095 | 一次 `POST /api/v2/chat/query` 请求,复现报告里的问题("I've uploaded our internal regional sales file for H1 2026. Compare it against the revenue numbers in the data warehouse for the same period and flag any regions with more than 5% variance."),针对一个所有文档在该问题下评分都低于 `_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE` 的测试知识库,应返回一个 `sources` 为空列表的响应。按第 10 节所述,这条标准针对的是低分噪音——它不宣称这道下限能排除掉原始报告里那两篇文档的复现版本,因为那两篇文档的分数,比任何同时也能满足 AC-FV10-089 那份测试数据的下限值都要高。 |

## 8. 测试计划

### 8.1 单元测试 — 相关性下限

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-198 | unit | 一份 `relevance_score` 为 `[0.9, 0.4, 0.1]` 的测试数据,配合 `_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE`,产出的 `knowledge_base_evidence` 应有 2 项,对应 `0.9`/`0.4` 这两个来源(AC-FV10-089)。实现为 `tests/test_chat_query_with_files.py::test_chat_query_hybrid_comparison_excludes_low_relevance_knowledge_base_sources`(用的是一个 `_FixedScoreKnowledgeStore` 测试替身,而不是直接用 `InMemoryKnowledgeStore`——见第 10 节)。 |
| TC-FV10-199 | unit | `uploaded_file_evidence` 不受这道下限影响(AC-FV10-090/NFR-FV10-029)。这是靠结构保证的,不是一条专门的运行时测试——见第 10 节:第 6.1 节的下限只应用在 `knowledge_base_evidence` 那段推导式内部,完全不会碰到独立构造出来的 `uploaded_file_evidence` 变量。 |

### 8.2 单元测试 — `FederatedQueryAgent.zero_row_join_caveat`

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-200 | unit | 一个伪造的 LLM 客户端返回一条包含 `JOIN` 的 SQL 语句,针对两个都非空、但完全不重合的测试数据;查询执行后返回 0 行;`zero_row_join_caveat` 应为 `True`(AC-FV10-091)。实现为 `tests/test_federated_query_agent.py::test_zero_row_join_caveat_true_when_join_keys_do_not_match_and_sources_are_non_empty`。 |
| TC-FV10-201 | unit | 同一份测试数据,但两侧的 join key 能匹配上,产出非空结果;`zero_row_join_caveat` 应为 `False`(AC-FV10-092)。实现为 `test_zero_row_join_caveat_false_when_join_keys_match`。 |
| TC-FV10-202 | unit | 同一份测试数据,但 Postgres 侧数据源为空(0 行),查询返回 0 行;`zero_row_join_caveat` 应为 `False`(AC-FV10-093)。实现为 `test_zero_row_join_caveat_false_when_the_postgres_side_is_empty`。 |
| TC-FV10-203 | unit | 一次生成的 SQL 不包含 `JOIN` 子串(比如单表 `WHERE` 查询),返回 0 行;不管数据源行数是多少,`zero_row_join_caveat` 都应为 `False`。实现为 `test_zero_row_join_caveat_false_when_the_generated_sql_has_no_join`。 |

### 8.3 集成测试 — 答案合成指令与 HTTP 响应

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-204 | integration (HTTP) + unit | `POST /api/v2/chat/query`,配合一次不匹配的联邦 join,应返回 `table_result.rows == []`,答案文字能证明提示指令确实传到了答案合成环节(AC-FV10-094)。实现为 `tests/test_chat_query_federated.py::test_federated_join_key_mismatch_flags_zero_row_join_caveat_in_answer_synthesis`,用了一个会检测自己的 system prompt 里有没有提示措辞的 LLM 桩。另外在 `tests/test_answer_synthesis.py` 里补了对 `GroundedAnswerSynthesizer.synthesize()` 新增的 `extra_instructions` 参数的直接单元测试(`test_synthesize_appends_extra_instructions_to_the_system_message`、`test_synthesize_without_extra_instructions_does_not_alter_the_system_message`、`test_fallback_answer_states_no_matching_rows_when_extra_instructions_and_empty_table`)。 |
| TC-FV10-205 | integration (HTTP) | `POST /api/v2/chat/query`,附带一份结构化文件、一个用日常 RAG 触发词("internal")措辞的问题,以及一个固定返回三条分数分别为 `[0.9, 0.4, 0.1]` 的证据的知识库桩,应返回的 `data.evidence_list` 只包含 `0.9` 和 `0.4` 这两个来源(AC-FV10-089/AC-FV10-095,跟 TC-FV10-198 合并成了一条 HTTP 层测试,而不是拆成一条单独的更底层单元测试——因为这道过滤是 `_handle_file_data_chat_query` 内部的行内逻辑,不是一个独立函数)。实现为 `tests/test_chat_query_with_files.py::test_chat_query_hybrid_comparison_excludes_low_relevance_knowledge_base_sources`。 |

### 8.4 回归测试

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-206 | regression | `tests/test_chat_query_with_files.py`、`tests/test_chat_query_federated.py`、`tests/test_chat_query_file_rag_analytics.py` 中所有既有测试都应继续通过。这里跟 TC-FV10-199 不一样,不是靠结构保证的:针对最初提议的 `0.35` 下限跑一遍全量测试套件,确实跑挂了 `tests/test_chat_query_file_rag_analytics.py::test_file_query_layers_in_knowledge_base_rag_evidence_for_a_why_question`——这正是第 10 节记录的那次回归,也是这道下限数值被修改的原因。 |
| TC-FV10-207 | regression | 所有断言 `FederatedQueryAgentOutput` 的 `table_result`/`error_code`/`degraded` 字段的既有测试,应保持不变、继续通过——`zero_row_join_caveat` 是新增字段,默认值为 `False`。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-084 | AC-FV10-089, AC-FV10-095 | TC-FV10-198, TC-FV10-205, TC-FV10-206 |
| FR-FV10-085 | AC-FV10-091, AC-FV10-092, AC-FV10-093 | TC-FV10-200, TC-FV10-201, TC-FV10-202, TC-FV10-203, TC-FV10-207 |
| FR-FV10-086 | AC-FV10-094 | TC-FV10-204 |
| NFR-FV10-029 | AC-FV10-090 | TC-FV10-199 |

## 10. 实现注记

- 本 Spec 是在实现之前写的,而且第 6 节的改动落地之前,已经确认过 TC-FV10-198 到 TC-FV10-205 针对实现之前的代码,会因为预期的原因失败(当时既没有相关性下限,`FederatedQueryAgentOutput` 也没有 `zero_row_join_caveat` 字段)——这是 SDD+TDD 的"红灯"步骤,遵循本项目已经确立的 TDD 纪律(参见 [Spec FV10.10 第 9 节](10-per-file-relevance-filtering-in-mixed-selections.spec.zh-CN.md) 里同样做法的先例)。
- **第 6.1 节最初提议的 `0.35` 下限,在实现过程中、在第 8 节任何测试真正拿去跑真实代码之前,就被修正成了 `0.15`。**第 6.1 节当时已经标注过这个数值"是一个起始值,还没有针对生产环境的真实检索数据做过实证调优"——这个担忧后来被证明是站得住脚的。对照 `InMemoryKnowledgeStore` 真实的评分公式(`knowledge.py:362`)实测:
  - `tests/test_chat_query_file_rag_analytics.py::test_file_query_layers_in_knowledge_base_rag_evidence_for_a_why_question` 里既有的回归测试数据——一个真实的"为什么营收变化了"问题,对应一篇真正切题的文档——打分是 **0.2267**,低于 `0.35`。针对 `0.35` 这版实现跑一遍全量测试套件,确实跑挂了这条测试:`assert len(data["evidence_list"]) == 1` 产出了 `0 == 1`。
  - 把*报告里那个 bug 本身那两篇不相关的文档*复现出来,针对报告里的原始问题打分,结果分别是 **0.3502** 和 **0.4011**——两者都高于 `0.35`。另外拿一篇不相关的支持工单类文档做对照,打分是 **0.3548**。
  - 原因在于:这套评分体系奖励的是一篇文档的词汇覆盖广度(词越多,跟任何问题之间偶然产生的关键词重合和哈希嵌入桶重合就越多),而不是它跟问题真正切题的程度——一段简短、切题的文本片段,完全可能比一篇篇幅更长、跑题的文档打分更低。没有任何一个单一的下限数值,能同时满足"AC-FV10-089 那份测试数据"、"保住 0.2267 分的那条既有回归测试"、"排除掉 0.35–0.40 分的那些复现噪音"这三个条件;`0.15` 的选择,满足了前两个(其中"不破坏一条既有的、正在通过的测试"是硬约束),代价是第三个条件不再成立——第 6 节的设计文档修订版已经把这一点记录成了一个真实存在、影响不小的已知限制,而不是一个假设性的问题。
  - 这跟 [Spec FV10.9 第 10 节](09-data-domain-signal-safety-net-for-the-relevance-gate.spec.zh-CN.md)、[Spec FV10.11 第 10 节](11-value-sample-aware-schema-context.spec.zh-CN.md) 各自记录的、由测试数据构造过程引出的修正是同一类性质,被抓到的时间点也跟 FV10.11 一样:在构造某条测试数据的过程中,在这条测试数据(或者任何其他新测试)被拿去跑生产代码之前。
- TC-FV10-198 和 TC-FV10-205 最终被实现成了同一条 HTTP 层测试,而不是分处两个不同层级的两条测试,因为这道相关性下限过滤本身就是 `_handle_file_data_chat_query()` 内部的行内逻辑,不是一个有独立可测边界的函数——具体见第 8.3 节修订后的描述。
- FR-FV10-085 的 `zero_row_join_caveat` 计算,只有在结果本身已经为空时(第 6.3 节 `and` 链里 `not rows` 先短路判断)才会多发出两次 `COUNT(*)` 查询——在结果非空的常见路径上,不会增加任何额外开销。
- 本 Spec 实现完成后,整个项目测试套件里不需要连真实 Postgres、也不需要构建好的前端包的 1396 个测试全部通过;跟本次改动无关的既有失败(Postgres 凭据类测试、前端构建产物类断言测试、针对无关既有代码的静态分析测试、一个针对无关既有文件的 markdown 链接解析测试)在数量和具体项上,跟本 Spec 改动之前完全一致,没有变化。
