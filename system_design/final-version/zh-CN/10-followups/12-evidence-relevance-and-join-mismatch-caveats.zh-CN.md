# 10.12 混合文件/数仓对比回答的证据相关性过滤与 Join 不匹配提示

English version: [../../en/10-followups/12-evidence-relevance-and-join-mismatch-caveats.en.md](../../en/10-followups/12-evidence-relevance-and-join-mismatch-caveats.en.md)

## 1. 观察到的问题

一位分析师上传了 `regional_sales_h1_2026.csv`（列：`region`、`month`、`revenue`、`orders`），并提问："I've uploaded our internal regional sales file for H1 2026. Compare it against the revenue numbers in the data warehouse for the same period and flag any regions with more than 5% variance."（我上传了我们内部的 H1 2026 地区销售文件，把它跟数仓里同期的营收数字做对比，标出差异超过 5% 的地区。）

返回结果里有两个互相独立的问题：

1. **答案文字断言了一个系统从未真正验证过的结论。**回答说"SQL 查询执行后……返回了 0 行，说明没有地区的差异超过 5%"。但上传文件跟数仓表做 `JOIN` 时，**join key 不匹配**同样会产生 0 行结果——比如文件里写的是 `"US-West"`，数仓里存的是 `"us-west"` 或 `"West"`，又或者 `month` 的格式不一致。整条链路里没有任何环节区分过"每个地区都真的比较过、没有一个超过 5%"和"根本一行都没匹配上"这两种情况，但答案却自信地断言了前者。
2. **"Sources"面板显示了两篇跟这个问题毫无关系的文档**："July 2026 Revenue Drop — Campaign Pause Root Cause Analysis" 和 "2025 Holiday Season Revenue and Support Surge — Post-Mortem"。这两篇文档都没有讨论地区销售差异、上传的文件，或者答案文字里实际用到的任何内容，但它们照样被检索出来并展示了。

这两个缺陷都是通过直接阅读这个问题实际走过的代码路径——`src/chatbi/api/http.py` 里的 `_handle_file_data_chat_query()`——复现的，而不是靠重放某一次具体的 LLM 调用：两个根因都是结构性的（只要满足触发条件就会出现，跟某一次模型具体返回了什么无关），不是某次模型偶然犯的错。

## 2. 已经具备的基础

### 2.1 为什么一次毫不相关的知识库检索会被触发

`_handle_file_data_chat_query()` 用的是跟其他地方完全一样的通用分类器 `QuestionClassifier.classify()`（`src/chatbi/orchestration/routing.py:97-125`），它并不知道这次调用点是在回答一个"文件 vs 数仓"的对比问题，而不是一个"为什么发生了 X"的文档类问题：

```python
task_types = question_classifier.classify(question)
```

`QuestionClassifier._RAG_KEYWORDS`（`routing.py:61-65`）里包含了一个很普通的单词 `"internal"`：

```python
_RAG_KEYWORDS = (
    "why", "reason", "cause", "explain", "what happened",
    "incident", "report", "document", "context", "background",
    "according to", "internal", "analysis says", "review",
)
```

报告里的问题写的是"our **internal** regional sales file"（我们**内部**的地区销售文件）——这只是分析师用来表示"这是我们自己的数据，不是第三方的"的一个日常用词——但光凭这一个词，分类结果里就被加上了 `TaskType.RAG_EXPLANATION`。`_RAG_KEYWORDS` 里还有 `"report"` 和 `"review"`，这两个词同样很可能出现在分析师描述文件对比问题时的日常措辞里（比如 "compare this report"、"review the variance"），所以这不是巧合命中一个词那么简单，而是一份为"文档解释类问题"设计的关键词表，跟一个同时要处理"用日常业务语言表述的对比类问题"的调用点之间，本来就存在结构性的错配。

### 2.2 为什么检索出来的文档不管相不相关都会被展示

一旦命中了 `TaskType.RAG_EXPLANATION`，`http.py:2554-2570` 就会发起一次对文件对比场景毫无感知的、面向全组织知识库的语义检索：

```python
if TaskType.RAG_EXPLANATION in task_types and active_knowledge_store is not None:
    retrieval_result = active_knowledge_store.retrieve(
        RetrievalQuery(
            question=question,
            requesting_user_id=user_id,
            user_role=role,
            top_k=5,
            conversation_context=" ".join(
                message["content"] for message in conversation_context
            ),
        ),
        trace_id=trace_id,
    )
    knowledge_base_evidence = tuple(
        EvidenceItem(..., relevance_score=item.relevance_score)
        for item in retrieval_result.evidence_list
    )
```

`InMemoryKnowledgeStore.retrieve()`（`src/chatbi/knowledge.py:280-295`）按一个综合评分排序并保留前 `top_k` 个，但它唯一的下限只是 `relevance_score <= 0`（`knowledge.py:363`）——只要有一丝丝关键词或向量层面的重合就能过线。对于一个只有五篇文档左右的知识库，`top_k=5` 几乎等于把整个知识库都返回了，只是排了个序，没有任何有意义的截断。

这份 `knowledge_base_evidence` 元组会被原样传进 `ResultMerger.merge()`（`src/chatbi/orchestration/result_merger.py:53-64`）——它自己的文档字符串（`result_merger.py:1-19`）写得很明确："This module does not execute SQL, call an LLM, or narrate anything itself — it only shapes whichever agent outputs already ran into one tagged context."（这个模块不执行 SQL、不调用 LLM、也不生成任何叙述——它只是把已经跑完的各个 agent 输出整理成一份带标签的统一上下文。）`_tag_evidence()`（`result_merger.py:111-121`）印证了这一点——它无条件地把 `uploaded_file_evidence` 和 `knowledge_base_evidence` 拼接在一起，完全没有相关性分数这个参数：

```python
def _tag_evidence(
    self,
    uploaded_file_evidence: tuple[EvidenceItem, ...],
    knowledge_base_evidence: tuple[EvidenceItem, ...],
) -> tuple[SourcedEvidenceItem, ...]:
    return tuple(
        SourcedEvidenceItem(evidence=item, is_uploaded_file=True) for item in uploaded_file_evidence
    ) + tuple(
        SourcedEvidenceItem(evidence=item, is_uploaded_file=False)
        for item in knowledge_base_evidence
    )
```

`evidence_payload`（`http.py:2604-2616`）会把 `merged.evidence_items` 里的每一项都无条件渲染进 API 响应的"Sources"列表。这整条链路里没有任何一步检查过：最终合成出来的答案文字里，到底有没有真的用到某一条证据——`ResultMerger` 是在答案合成**之前**运行的，不是之后，这是设计使然（§2 那句文档字符串已经说得很清楚：它只**整理上下文**，不做叙述）。只要 `TaskType.RAG_EXPLANATION` 被触发，低相关性、不相关的证据就一定会一路传到界面上。

### 2.3 为什么一次 0 行的 join 结果会被叙述成"没有差异"

`FederatedQueryAgent.run()`（`src/chatbi/agents/federated_query_agent.py:138-206`）把数仓的行物化成 `db_{table}`、把文件物化成 `file_{file_id}`（`_register_views`，第 164-171 行），让 LLM 生成一条 JOIN/对比 SQL 语句（`_generate_sql`，第 261-300 行），执行它，然后把 DuckDB 返回的东西原样带回去：

```python
try:
    columns, rows = fetch_table(connection, sql_text)
except QueryResourceExceededError:
    ...
except InvalidGeneratedSqlError:
    ...
return FederatedQueryAgentOutput(
    degraded=False,
    table_result=TableResult(columns=columns, rows=rows),
    federated_sql=sql_text,
)
```

这个方法里完全没有任何地方去比较两个数据源视图的行数和最终结果行数。一条 `JOIN ... ON f.region = d.region`，如果文件里存的是 `"US-West"`、数仓里存的是别的拼法，产出的是一条语法和语义都完全合法、但返回 0 行的查询——在这一层，这跟"确实比较了每个地区，结果都没超过 5%"完全无法区分。下游的答案合成 LLM 调用（`src/chatbi/answer_synthesis.py`）在这两种情况下拿到的都是同一份空的 `TableResult`，没有任何信号告诉它这是两种不同的情况，于是它就会自由发挥，挑一个读起来最顺、能解释"一张空表"的说法——在这次报告的案例里，就是"没有差异"。

## 3. 设计：在证据渲染的那一刻加一道相关性分数下限

与其去试图把 `_RAG_KEYWORDS` 打磨得更完美——任何一份固定的英文关键词表，迟早都会包含一个分析师出于无关原因使用的词，这正是 [10.8](08-question-relevance-gate-before-file-branch-routing.zh-CN.md) 和 [10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.zh-CN.md) 在给*文件路由*那道门做设计时已经得出的同一个教训——不如直接修复*真正传达给用户的那个症状*：不管检索是因为什么原因被触发的，跟答案没有实际关联的证据都不该被当成"依据"展示出来。

在 `_handle_file_data_chat_query()` 把检索结果转成 `EvidenceItem` 的那一刻（`http.py:2571-2580`），也就是它进入 `ResultMerger` 之前，给 `knowledge_base_evidence` 加一道最低相关性分数下限：

```python
_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE = 0.15  # 数值在实现过程中被修正过——见第 9 节

knowledge_base_evidence = tuple(
    EvidenceItem(..., relevance_score=item.relevance_score)
    for item in retrieval_result.evidence_list
    if item.relevance_score >= _MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE
)
```

这个改动刻意只限定在混合文件对比这条路径上（`_handle_file_data_chat_query`）——也就是这次报告的答案实际走过的那个调用点——不会改变主编排器自己那条独立触发的 RAG 逻辑。`uploaded_file_evidence`（来自 `FileScopedRetriever`，只检索用户自己附带的非结构化文件）不受影响：跟面向全组织的知识库检索不同，从用户明确附带到*这次请求*的文件里检索出来的证据，天然就是相关的——这跟 [10.8 第 4 节](08-question-relevance-gate-before-file-branch-routing.zh-CN.md) 对非结构化文件已经采用的推理是一样的。

这个改动完全不涉及 `_RAG_KEYWORDS` 或 `QuestionClassifier` 本身——一个恰好包含"internal"的混合对比问题依然会触发知识库检索，但一次真的什么相关内容都没找到的检索，现在会正确地返回空结果，而不是拿排名最靠前但毫不相关的文档去填充响应。

## 4. 设计：join 返回 0 行时给出提示

`FederatedQueryAgentOutput` 新增一个字段，由 `FederatedQueryAgent.run()` 在物化好数据源视图之后、生成 SQL 之前立即计算：

```python
@dataclass(frozen=True, slots=True)
class FederatedQueryAgentOutput:
    ...
    zero_row_join_caveat: bool = False
```

计算规则：最终查询返回 0 行，生成的 SQL 文本里包含 `JOIN` 关键词（大小写不敏感），并且两个数据源视图（`db_{table}`、`file_{file_id}`）在 join 之前各自都至少有一行数据。第三个条件很关键：如果任何一个数据源本身就是空的，那么空结果就是*正确的、没有歧义的*答案（"你的文件在这个时间段没有数据"）——这个提示只是针对"单看'0 行'这个结果本身很容易被误读"的那种情况,而不是针对每一次空结果。

当 `zero_row_join_caveat` 为 `True` 时，`_handle_file_data_chat_query()` 会给答案合成的 prompt（`answer_synthesis.py`）传入一条明确指令，而不是任由 LLM 自由发挥去给一张空表编一个解释：

> 这次对比查询在 join 之后一行都没有匹配上，尽管文件和数仓表在这个时间段里各自都是有数据的。请明确说明：没有在 join key 上找到任何匹配的记录——不要说这意味着所有数值都在某个阈值以内，因为 join key 不匹配（比如文件和数仓列之间拼写、大小写或日期格式不一致）会产生一模一样的 0 行结果。建议用户核实两边共用的列在数值/格式上是否一致。

这样一来，原本无法区分的两条代码路径，现在会产生两种可以被观察到、不一样的回答：join 真的匹配上了行、而且确实没有超过阈值时，是真正的"没有差异"叙述；join 根本没匹配上任何东西时，是一条明确的"什么都没匹配上"的提示。

## 5. 验证

按本项目的 SDD+TDD 惯例，[Spec FV10.12](../../../../spec/final-version/zh-CN/10-followups/12-evidence-relevance-and-join-mismatch-caveats.spec.zh-CN.md) 在实现之前就把上面第 3、4 节转化成了功能需求、验收标准和测试用例。大致包括：

- 相关性分数下限的单元测试（`tests/test_chat_query_with_files.py`）：一个假的知识库返回 `relevance_score` 为 `[0.9, 0.4, 0.1]` 的证据，产出的 `knowledge_base_evidence` 只应包含达到或超过下限的那些项；同一份测试数据下 `uploaded_file_evidence` 不受影响。
- `FederatedQueryAgent` 的单元测试（`tests/test_federated_query_agent.py`）：一个假的 LLM 客户端返回包含 `JOIN` 的 SQL，针对两个都非空但匹配不上的数据源视图，`zero_row_join_caveat` 应为 `True`；同一套测试数据换成 join key 能匹配上、结果非空时应为 `False`；某个数据源本身就是空的、以及生成的 SQL 里根本没有 `JOIN` 关键词这两种情况，也都应为 `False`。
- HTTP 层测试（`tests/test_chat_query_with_files.py`、`tests/test_chat_query_federated.py`），端到端覆盖相关性下限和 join 不匹配提示，其中一条专门确认这条提示指令确实传到了答案合成 prompt 里。

第 9 节记录了在写第一条测试用例数据、还没有拿去跑任何真实代码之前，就发现相关性下限具体数值需要修正的经过。

## 6. 已知限制——本次刻意不解决

- **相关性下限是一个固定常数，不是自适应的——而且按第 9 节的发现，在这套评分算法下，它本身就是一个偏弱的信号。**`InMemoryKnowledgeStore` 的"关键词+哈希嵌入"评分方式，奖励的是一篇文档的词汇覆盖广度，而不是它跟问题的真实主题相关性：实现过程中实测，一段简短、精确切题的文本片段得分是 0.2267，而*报告里那个 bug 本身那两篇不相关文档*的复现版本，针对同一个问题却分别得到了 0.3502 和 0.4011。没有任何一个单一的下限数值能既保住前者、又排除掉后两者——第 9 节记录了最终选择 0.15 来保住前者，代价是不再能可靠地排除后两者。这比本节最初"是一道有原则的阈值，不是语义层面的判断"这种表述所暗示的要严重得多，也比 [10.8 第 6 节](08-question-relevance-gate-before-file-branch-routing.zh-CN.md) 记录的那类限制更棘手——那里的一次误判是优雅地降级到主编排器；这里的下限，很可能压根就不会在它本来要解决的那个具体案例上生效。
- **join 不匹配提示只针对结果完全为空的情况。**如果 join 匹配上了*一部分*行、却悄悄漏掉了另一部分（比如五个地区里三个匹配上了，两个没匹配上），产出的是一份非空、看起来很合理的结果，完全不会触发任何提示——局部不匹配本质上比完全不匹配更难判断，依然不在范围内。（这一条原本还列了"只针对字面上出现 `JOIN` 关键词"这个限制——已经被 [10.14](14-comparison-query-detection-beyond-literal-join.zh-CN.md) 关上：针对这个具体场景做实盘复测时，发现一条基于 `EXCEPT` 的对比查询复现了这个 bug。）
- **`_RAG_KEYWORDS` 本身没有动。**这份设计修复的是*展示什么*，不是*检索什么*——底层那个过于宽泛的触发条件（"internal"、"report"、"review"）依然存在，还会继续在混合文件对比问题上触发不必要的知识库检索。按第 9 节的发现，这次检索现在**并不能**像第 3 节最初假设的那样可靠地对用户无害——未来的后续工作应该把收窄或交叉验证 `_RAG_KEYWORDS` 本身（也就是 [10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.zh-CN.md) 给文件路由门用过的那种交叉验证信号思路）当成优先级更高的修复，而不是一个可选项。

## 7. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-084 | 在 `_handle_file_data_chat_query()` 中，`relevance_score` 低于固定最低下限的 `knowledge_base_evidence` 条目，必须在传给 `ResultMerger.merge()` 之前被排除。 | 已实现 |
| FR-FV10-085 | `FederatedQueryAgentOutput` 必须暴露一个 `zero_row_join_caveat: bool` 字段，仅当最终结果为 0 行、生成的 SQL 包含 `JOIN` 关键词、且两个数据源视图在 join 之前都至少有一行数据时为 `True`。 | 已实现 |
| FR-FV10-086 | 当 `zero_row_join_caveat` 为 `True` 时，答案合成 prompt 必须收到一条明确指令，不得把结果表述为"确认了阈值内的比较结果"，而应说明没有在 join key 上找到匹配的记录。 | 已实现 |
| NFR-FV10-029 | 本次新增的相关性下限不得改变 `uploaded_file_evidence`（经由 `FileScopedRetriever` 检索、只针对用户自己附带的非结构化文件的证据）——只过滤来自全组织检索的 `knowledge_base_evidence`。 | 已实现 |

## 8. 现状：已修复并验证——阈值经过修正

通过直接阅读这次报告的答案实际走过的调用点（`_handle_file_data_chat_query`）的代码发现，不是靠重放某一次具体的 LLM 调用——两个根因都是结构性的，只要满足各自的触发条件就会复现，跟模型具体返回了什么无关。按本项目一贯的 SDD+TDD 顺序先写设计、后写 Spec：[Spec FV10.12](../../../../spec/final-version/zh-CN/10-followups/12-evidence-relevance-and-join-mismatch-caveats.spec.zh-CN.md) 把上面第 3、4 节转化成了正式的需求、验收标准和测试计划，然后两者都已实现。修复涉及 `src/chatbi/api/http.py`、`src/chatbi/files/contracts.py`、`src/chatbi/agents/federated_query_agent.py`、`src/chatbi/answer_synthesis.py`；`tests/test_chat_query_with_files.py`、`tests/test_chat_query_federated.py`、`tests/test_federated_query_agent.py`、`tests/test_answer_synthesis.py` 里新增了对应测试。整个项目的测试套件（1396 个测试，不含本项目自己的惯例早已记录为无关的、既有的 Postgres 凭据类和前端构建产物类失败）全部通过。第 9 节记录了在写相关性下限第一条测试数据、还没有拿去跑任何生产代码之前，就发现需要修正的经过。

## 9. 写相关性下限第一条测试时发现的一次修正

第 3 节最初的数值 `0.35`，在提出的时候没有对照 `InMemoryKnowledgeStore` 实际的评分行为做过实测。在给 `tests/test_chat_query_file_rag_analytics.py` 里一条既有的回归测试数据——一个真实的"为什么营收变化了"问题，对应一篇写着"Revenue dropped in March because a marketing campaign was paused for three weeks."的文档——针对已经实现的下限跑一遍时，发现这套知识库的 `retrieve()` 给这对问题/文档打出的分数是 **0.2267**，低于最初提议的下限，这会悄悄丢掉一条既有测试已经断言过应该被返回的证据。

把*报告里那个 bug 本身那两篇不相关的文档*（一篇 7 月营收下滑根因分析，一篇 2025 假期后复盘）复现出来，针对报告里那个原始问题去打分，结果分别是 **0.3502** 和 **0.4011**——两者都**高于** `0.35`。另外拿一篇完全不相关的支持工单类文档做对照，打出的分数是 **0.3548**。原因在于：`InMemoryKnowledgeStore` 的 `relevance_score`（`knowledge.py:362`，`keyword_score * 0.60 + vector_score * 0.35 + source_score`）奖励的是一篇文档的总体词汇量——文档越长，跟几乎任何问题之间偶然产生的关键词重合和哈希嵌入桶重合就越多——而不是奖励它跟问题真正切题的程度。一段简短、精确切题的文本片段，完全可能比一篇篇幅更长、措辞泛泛相关但实际跑题的文档打分更*低*。

没有任何一个单一的下限数值能同时满足这两个约束（0.2267 < 0.3502 < 0.4011）。`_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE` 最终被设成 `0.15`——低于那条既有回归测试的分数，保住现有行为不被破坏，同时依然能排除掉那些接近于零、纯属巧合的匹配。这已经不是第 3 节最初描述的那个设计了：它是一个为了避免回归而校准出来的下限，不是一个被证明能解决触发本次调查那个原始 bug 的下限。上面第 6 节已经据此做了修正，第 8 节"已修复并验证"这句话也应该按这个更窄的范围来理解——*"Sources"被不相关内容污染*这个症状，对于真正低分的噪音是修复了；但报告里那两篇原始文档的复现版本，单靠这次修复并不能被可靠地排除掉。
