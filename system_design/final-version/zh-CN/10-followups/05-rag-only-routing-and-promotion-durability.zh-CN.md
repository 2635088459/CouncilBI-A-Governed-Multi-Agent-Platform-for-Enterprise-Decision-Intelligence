# 10.5 纯文档问答路由与知识库提升的持久性

## 1. 解决的问题

在对 10.1–10.4 做 Docker 端到端验证时，"文档已经在知识库里"和"RAG 真的能从这份文档里答出来"之间发现了两个缺陷：

1. **每个问题都被强制先过 SQL 这一关，哪怕是纯文档类问题也不例外。** 问"Nimbus 产品单页里关于定价是怎么说的？"——这种问题跟任何 SQL 表都没关系——但整条链路依然会先走 SQL 生成。LLM 根本没有合理的 SQL 可写，生成了非法 SQL，被 guardrail 拦下，整个请求在 RAG 还没来得及跑之前就被拒绝了。`rag_agent` 压根没有被执行的机会。
2. **把文件提升进知识库这个操作，可能悄无声息地生成一份永久空白、检索不到的文档。** 一份文件曾经成功提升过一次，之后（比如 backend 进程重启之后）再尝试提升，本该报错的地方却没有报错——而是正常创建了一条 `knowledge.documents` 记录，但里面 0 个 chunk：文档"存在"、"已入库"，却永远不会被任何检索命中，而且没有任何错误提示告诉你为什么。

本文档记录这两处修复的设计。

## 2. 已经具备的基础

**路由这一侧：**
- `QuestionClassifier.classify()` 不管问题内容是什么，都会无条件把 `TaskType.SQL_QUERY` 加进分类结果里。
- `ExecutionPlanBuilder.build()` 永远把 SQL 步骤放在执行计划的最前面，而且每一个扇出（fanout）步骤（RAG、VISUALIZATION、ANALYTICS、FILE_DATA）都无条件声明 `depends_on=(AgentName.SQL,)`。
- `PlanExecutor.execute()` 把 SQL 阶段的任何失败都当成整个计划的致命错误：一旦失败，就按声明顺序跳过后面所有剩余步骤,而不是只跳过那些真正依赖 SQL 的步骤。
- `AnswerAssemblyVerifier` 强制要求每个回答都必须带非空的 `sql_text` 和 `table_result.columns`——没有"仅靠证据支撑也算合法回答"的备选路径。

**知识库提升这一侧：**
- `KnowledgePromotionService.promote_file()` 从 `FileVectorSource`（一个接口；`create_app()` 里接的实现是 `InMemoryFileVectorSink`）读取已经切好片、算好向量的文本，复制进持久化的知识库（`InMemoryKnowledgeStore` + `knowledge.*` 系列 Postgres 表）。这份缓存只在文件第一次上传处理时，由 `FileProcessingWorker` 填充一次——而且它是进程内内存,backend 一重启就没了。
- `promote_file()` 原来没有对"`chunks_with_vectors_for_file(file_id)` 返回空"这种情况做任何检查。它照样创建了 `knowledge.documents` 记录、照样把（空的）`promoted_to_doc_id` 关联挂上去——生成了一份除了 RAG 检索真正会读的那张表（`knowledge.doc_chunks`）之外，哪里看起来都"正常存在"的文档。

## 3. 设计：把"需要 SQL"和"需要 RAG"拆开判断

`QuestionClassifier` 现在会先判断这个问题到底需不需要 SQL 数据，而不是默认它总是需要：

```python
has_data_signal = _contains_any(question, DATA_DOMAIN_KEYWORDS)   # revenue, order, ticket, total, count, ...
is_chart = _contains_any(question, CHART_KEYWORDS)
is_analytics = _contains_any(question, ANALYTICS_KEYWORDS)
is_rag = _contains_any(question, RAG_KEYWORDS)                    # why, explain, document, ...

needs_sql = has_data_signal or is_chart or is_analytics or not is_rag
```

最后一句 `not is_rag` 是关键：它意味着对任何不明确是 RAG 问题的情况，SQL 依然是**默认**要走的——所以纯数据问题（"营收按月是多少？"）和组合型问题（"为什么营收下滑了？"——既命中 RAG 关键词，又命中数据域关键词）的原有行为完全不变。只有当一个问题命中 RAG 关键词、但其它信号一个都没命中时，才会不再要求 SQL——就像 Nimbus 定价那个纯文档问题。

## 4. 设计：不需要 SQL 时，执行计划直接跳过 SQL 步骤

`ExecutionPlanBuilder.build()` 现在只有在分类结果里包含 `TaskType.SQL_QUERY` 时，才会把 SQL 步骤加进计划、并把每个扇出步骤的依赖设成 `depends_on=(AgentName.SQL,)`：

```python
needs_sql = TaskType.SQL_QUERY in task_types
sql_steps = (AgentPlanStep(AgentName.SQL, ExecutionStage.SQL),) if needs_sql else ()
sql_dependency = (AgentName.SQL,) if needs_sql else ()
# 每个扇出步骤现在传入 depends_on=sql_dependency，而不是写死的 (AgentName.SQL,)
```

对一个纯 RAG 计划来说，这样产出的是 `(RAG, VERIFIER)`，压根没有 SQL 步骤——`AgentName.RAG` 的 `depends_on` 是 `()`，所以 `PlanExecutor` 会立即执行它，不用等任何前置条件。`simple_orchestrator.py` 也做了对应改动：它现在会先分类问题，再决定要不要调用生成 SQL 的 LLM 请求，如果 `needs_sql` 是 false 就完全跳过那次调用——纯文档问题不再需要为一次它根本用不上的 SQL 调用付出成本，也不会被这次调用意外拦截。

`PlanExecutor.execute()` 本身不需要改动：它按每个步骤自己声明的依赖做的检查（`if any(dep not in completed_agents for dep in step.depends_on)`）本来就是对的，会正确遵循 `depends_on` 里写的内容。这个 bug 完全出在计划构建器"喂给"它的计划本身有问题，不是执行器解读依赖的方式有问题。

## 5. 设计：答案校验接受"仅靠证据支撑"的回答

`AnswerAssemblyVerifier._findings()` 原来无条件要求 `sql_text` 和 `table_result.columns` 非空。一个纯文档回答两者都没有——它靠的是 `evidence_list`。现在这两项检查改成有条件的：

```python
if not answer.evidence_list:
    if not answer.sql_text.strip():
        findings.append("sql_text is required.")
    if not answer.table_result.columns:
        findings.append("table_result.columns is required.")
```

一个靠 SQL 支撑的回答（`evidence_list` 为空，和以前一样）会被完全按照原来的方式检查——已有的校验测试不受影响。一个靠证据支撑的回答会完全跳过 SQL 相关的检查。而一个**既没有** SQL 输出、**也没有**证据的回答，依然会校验失败、置信度被压到 0.5——这是有意保留的错误场景，不是被悄悄放行了。

这个假设不是只藏在 `AnswerAssemblyVerifier` 一个地方。`VerifierAgentRunner`——在最终答案组装之前、执行计划**内部**跑的那个 agent 级校验步骤——只要构造它时传入的 `sql_text` 是非 `None` 的空字符串，就会独立报出 `"SQL text is missing."`。`_build_runners()` 原来传的是 `sql_text=sql_candidate`，而对纯文档问题，`sql_candidate` 是 `""`（不是 `None`）——所以这第二个校验器，通过另一条完全不同的代码路径，因为跟第一个校验器一模一样的原因把这个计划判定失败了。修复是调用点上的一行改动：`sql_text=sql_candidate or None`——`None` 表示"这里不适用"，空字符串才表示"缺失"，只有后者才应该算一条 finding。这是在写 `TC-FV10-159`（一个断言纯文档问题的 `answer.warnings == ()` 的编排器级测试）时才发现的，而且这条测试在只做了上面那一处改动的情况下确实失败了——这正是"设计文档要跟代码保持同步"这句话本该防住的那类问题。

第三处同类问题，是在前两处都已经修完、也都测试通过之后，通过对着真实运行的 Docker 服务做一次完整 HTTP 往返请求才暴露出来的：`RuntimeQueryResultRecord`（`src/chatbi/history/query_results.py`）——这是持久化下来、供 `GET /api/v2/query-results/{trace_id}` 回放某次历史 SQL 结果用的记录——它的 `__post_init__` 只要碰到空的 `sql_text` 就会抛 `ValueError("sql_text is required")`。`http.py` 里的 `runtime_query_result_record_from_response()` 本来就有一套"没什么好持久化的就返回 None"的约定——`if not isinstance(sql_text, str): return None`——用来处理响应里压根没有 `sql_text` 字段的情况，但一个空字符串依然满足 `isinstance(..., str)`，所以它照样往下走，去构造这条记录，然后这个没被捕获的 `ValueError` 就在 `/api/v2/chat/query` 上变成了一个赤裸裸的 `500 INTERNAL_ERROR`——这是这整条链路里唯一一处 bug 不是"答案不对"、而是"压根没有答案"的地方。修复是延续已有的那套约定：`if not isinstance(sql_text, str) or not sql_text.strip(): return None`。这条记录跟 `QueryAnswer` 不一样，没有 `evidence_list` 这种可以顶上去的替代支撑——它存在的意义就是回放一次 SQL 结果，所以"没有 SQL 结果可以持久化"正确的表达方式是干脆跳过创建这条记录，而不是放松它的校验。

三个互相独立的地方都假设了"每个回答都有 SQL 文本"，而且是靠三种不同类型的测试才一个一个抓出来的：一条针对校验器的单元测试、一条跑通完整答案组装路径的编排器级测试，以及——对于单元测试和编排器级测试都够不到的那一处，因为它藏在 HTTP 响应序列化里，不在 `QueryAnswer` 的构造过程里——一次对着真实跑起来的服务发的真实 HTTP 请求。这正好印证了第 7 节那条"已知限制"说明同样适用在这里：当一个不变式在不止一个地方被默认成立时，修好"这一处" bug 很少等于修好了全部。

## 6. 设计：提升失败时大声报错，而不是生成一份"死文档"

`KnowledgePromotionService.promote_file()` 现在在做任何事之前，先检查 `chunks_with_vectors_for_file()`：

```python
chunks_with_vectors = self._vector_source.chunks_with_vectors_for_file(file_id)
if not chunks_with_vectors:
    raise FileNotPromotableError(file_id)
```

这把一个悄无声息、永久性的数据完整性问题（一份永远不会被任何查询命中的文档，且 API 响应里没有任何提示说明原因），变成了在出错的那一刻立刻能看到、能采取行动的 `422 FILE_NOT_PROMOTABLE`。经测试确认，调用方正确的恢复方式是重新上传这份文件——这会让 `FileProcessingWorker` 在**当前**进程里重新跑一遍切片处理，把向量源重新填上，之后再提升就能成功，文档也真的可以被检索到了。

## 7. 已知限制——本次未修复

根本原因依然存在：`FileVectorSource`（`InMemoryFileVectorSink`）是进程本地的，从不持久化，所以一个文件切片+向量化后的内容，只在处理它的那个进程的生命周期内可以被用来做"提升"。第 6 节把这一点从"悄悄出错"变成了"明确报错"，但没有从根本上消除这个限制。真正持久化的修复方案——比如把 `FileVectorSource` 换成 Postgres 存储，或者在提升时基于持久化保存的原始文件字节按需重新切片——是一个更大的改动，不在本次范围内。

## 8. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-057 | `QuestionClassifier` 只有在问题命中数据域、图表或分析类信号，或者完全没有命中 RAG 信号时，才应判定需要 SQL；一个只命中 RAG 信号、没有其它信号的问题，分类结果里不应包含 `TaskType.SQL_QUERY`。 | 已实现 |
| FR-FV10-058 | 当分类结果里没有 `TaskType.SQL_QUERY` 时，`ExecutionPlanBuilder` 必须不生成 SQL 步骤，也不能把任何扇出步骤的依赖设为 `AgentName.SQL`。 | 已实现 |
| FR-FV10-059 | 当分类出的任务类型不包含 `TaskType.SQL_QUERY` 时，编排器不应发起用于生成 SQL 的 LLM 请求。 | 已实现 |
| FR-FV10-060 | 当 `evidence_list` 非空时，`AnswerAssemblyVerifier` 必须把 `sql_text`/`table_result` 为空的回答视为合法；但两者都缺失时依然要判定失败。 | 已实现 |
| FR-FV10-061 | 当文件的向量源里没有可复制的 chunk 时，`KnowledgePromotionService.promote_file()` 必须抛出 `FileNotPromotableError`，而不是创建一条知识库文档记录。 | 已实现 |
| FR-FV10-062 | 当这个问题没有规划 SQL 步骤时，`VerifierAgentRunner` 不应报出"SQL 缺失"这条 finding；编排器在这种情况下必须传入 `sql_text=None`，而不是空字符串。 | 已实现 |
| FR-FV10-063 | 当响应里的 `sql_text` 是空字符串或纯空白时，`runtime_query_result_record_from_response()` 必须返回 `None`，不得构造 `RuntimeQueryResultRecord`。 | 已实现 |
| NFR-FV10-021 | 这次纯 RAG 路由改动不能影响原本就同时需要 SQL 和 RAG 的问题（例如"为什么营收下滑了？"），也不能影响纯 SQL/图表/分析类问题的原有行为。 | 已通过回归测试验证 |
