# Spec FV10.5：纯文档问答路由与知识库提升的持久性

来源设计文档：
- [10.5 纯文档问答路由与知识库提升的持久性设计](../../../system_design/final-version/zh-CN/10-followups/05-rag-only-routing-and-promotion-durability.zh-CN.md)
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；本 Spec 修正 `QuestionClassifier`、`ExecutionPlanBuilder`、`AnswerAssemblyVerifier`、`VerifierAgentRunner`，以及 `KnowledgePromotionService.promote_file()`）
- [Spec FV10.1：RAG 按用户隔离](01-rag-per-user-isolation.spec.zh-CN.md)（本 Spec 第 6.4 节复用 `KnowledgePromotionService` 的归属标记行为，未做改动）

---

## 1. 目的

在对 FV10.1–FV10.4 做 Docker 端到端验证时，发现了两个缺陷，都出在"文档已经在知识库里"和"RAG 真的能从这份文档里答出来"之间：

1. 一个纯文档问题（例如"单页里关于定价是怎么说的？"）被路由去走一个它根本用不上的强制 SQL 步骤。LLM 生成了非法 SQL，被 guardrail 拒绝，请求在 RAG 还没来得及跑之前就被拒绝了。
2. 把文件提升进知识库这个操作，如果文件切片+向量化后的内容在当前提升所在的进程里已经不存在了（比如经历过一次重启），可能悄无声息地创建一份永久空白、检索不到的文档，且没有任何报错。

本 Spec 把这两处修复定义成可测试的需求。

## 2. 范围

**纳入范围：**
- 问题分类：判断一个问题到底需不需要 SQL，而不是默认它总是需要。
- 执行计划构建：当不需要 SQL 时，省掉 SQL 步骤（以及每个扇出步骤对 SQL 的依赖）。
- 编排器控制流：当不需要 SQL 时，跳过生成 SQL 的 LLM 调用。
- 最终答案校验：接受一个仅靠 `evidence_list` 支撑、没有 SQL 输出的回答。
- Agent 级校验：当没有规划 SQL 步骤时，不把"SQL 缺失"当成一条 finding。
- 知识库提升：当一个文件没有可提升的 chunk 时，报出明确错误，且不留下任何部分写入的状态。

**不纳入范围：**
- 让 `FileVectorSource` 在进程重启后依然持久化（见设计文档第 7 节"已知限制"）。本 Spec 只要求失败要"大声"且不产生副作用，不要求消除背后的这个限制本身。
- 除了新增"是否需要 SQL"这个信号（第 6.1 节）之外，对关键词列表本身做任何其它调整——针对检索质量去调优具体关键词，不属于本 Spec。
- 检索相关性排序逻辑（`InMemoryKnowledgeStore._rank_records`）——本 Spec 不改动。

## 3. 参与方

沿用父 Spec FV-10 第 3 节定义的参与方。不引入新参与方。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-057 | `QuestionClassifier.classify()` 只有在问题命中数据域关键词、图表关键词、分析类关键词之一，或者完全没有命中 RAG 关键词时，才应在返回结果里包含 `TaskType.SQL_QUERY`。一个命中了 RAG 关键词、但没有命中其它三类信号中任何一个的问题，返回结果里不得包含 `TaskType.SQL_QUERY`。 |
| FR-FV10-058 | 当输入的任务类型集合里没有 `TaskType.SQL_QUERY` 时，`ExecutionPlanBuilder.build()` 返回的计划里不得包含 SQL 步骤，也不得把任何扇出步骤的 `depends_on` 设为 `(AgentName.SQL,)`。当集合里有 `TaskType.SQL_QUERY` 时，行为跟本 Spec 之前完全一致。 |
| FR-FV10-059 | 当一个问题分类出的任务类型不包含 `TaskType.SQL_QUERY` 时，编排器不得为它发起生成 SQL 的 LLM 请求；这种情况下 `sql_candidate` 必须是空字符串，且跳过这次调用不应产生任何 `WarningMessage`。 |
| FR-FV10-060 | 当 `evidence_list` 非空时，`AnswerAssemblyVerifier` 必须把 `sql_text` 和 `table_result.columns` 均为空的回答视为通过其组装检查。当 `evidence_list` 为空、且 `sql_text`/`table_result.columns` 也为空时，依然必须像本 Spec 之前一样判定失败。 |
| FR-FV10-061 | 当 `FileVectorSource.chunks_with_vectors_for_file(file_id)` 对一个原本可提升的文件返回空元组时，`KnowledgePromotionService.promote_file()` 必须抛出 `FileNotPromotableError`，并且不得对 `VectorStore`、实时的 `InMemoryKnowledgeStore`、Postgres 的 `knowledge.*` 系列表、或该源文件的 `promoted_to_doc_id`，做任何创建、更新或写入操作。 |
| FR-FV10-062 | 当编排器为一个没有规划 SQL 步骤的问题构造 `VerifierAgentRunner` 时，必须传入 `sql_text=None`，而不是空字符串。`VerifierAgentRunner` 在收到 `sql_text=None` 时不得报出"SQL 缺失"这条 finding（这是已有行为——本 Spec 的调用点改动，正是为了避免触发空字符串那个分支）。 |
| FR-FV10-063 | 当响应里的 `sql_text` 字段缺失、不是字符串、或是空/纯空白字符串时，`runtime_query_result_record_from_response()` 必须返回 `None`，不得构造 `RuntimeQueryResultRecord`。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-021 | 本 Spec 的路由改动，不得改变任何同时需要 SQL 和 RAG 的问题（例如"为什么营收下滑了？"）分类出的任务类型、计划形态或最终回答；也不得改变任何纯 SQL、图表或分析类问题的上述结果。通过在本 Spec 改动落地后，重新跑一遍原本就覆盖组合路径和纯 SQL 路径的回归测试来验证。 |

## 6. 数据契约

### 6.1 `QuestionClassifier`——是否需要 SQL 的信号

```python
_DATA_DOMAIN_KEYWORDS = (
    "revenue", "order", "orders", "refund", "active users",
    "support", "ticket", "case volume", "total", "count",
    "how many", "average", "sum", "rate",
)

def classify(self, question: str, *, file_ids: tuple[str, ...] = ()) -> frozenset[TaskType]:
    is_rag = self._contains_any(normalized, self._RAG_KEYWORDS)
    is_analytics = self._contains_any(normalized, self._ANALYTICS_KEYWORDS)
    is_chart = self._contains_any(normalized, self._CHART_KEYWORDS)
    has_data_signal = self._contains_any(normalized, self._DATA_DOMAIN_KEYWORDS)

    needs_sql = has_data_signal or is_chart or is_analytics or not is_rag
    # 当且仅当 needs_sql 为 True 时，TaskType.SQL_QUERY 才会被加进结果集合。
```

`not is_rag` 是保持默认行为不变的那一句：任何没有命中 RAG 关键词的问题，依然跟本 Spec 之前一样需要 SQL。

### 6.2 `ExecutionPlanBuilder`——有条件的 SQL 步骤

```python
def build(self, task_types: frozenset[TaskType] | TaskType) -> ExecutionPlan:
    needs_sql = TaskType.SQL_QUERY in task_types
    sql_steps = (AgentPlanStep(AgentName.SQL, ExecutionStage.SQL),) if needs_sql else ()
    sql_dependency: tuple[AgentName, ...] = (AgentName.SQL,) if needs_sql else ()
    # 每个扇出步骤（RAG、VISUALIZATION、ANALYTICS、FILE_DATA）现在都传
    # depends_on=sql_dependency，而不是写死的 (AgentName.SQL,)
```

### 6.3 编排器——有条件的 SQL 生成

```python
task_types = self._classifier.classify(request.question)
needs_sql = TaskType.SQL_QUERY in task_types
if needs_sql:
    sql_candidate, llm_warning = self._build_sql_candidate(request, active_trace_id, conversation_messages_tuple)
else:
    sql_candidate, llm_warning = "", None
```

表格结果的组装也是同样的逻辑：当 `not needs_sql` 时，`table_result` 是 `TableResult(columns=(), rows=())`，且不会尝试执行只读查询（不会因为跑了个空 SQL 字符串而多出一条虚假的 `INTERNAL_ERROR` 警告）。

### 6.4 `AnswerAssemblyVerifier`——接受仅靠证据支撑的回答

```python
def _findings(self, answer: QueryAnswer) -> tuple[str, ...]:
    findings: list[str] = []
    if not answer.answer_text.strip():
        findings.append("answer_text is required.")
    if not answer.evidence_list:
        if not answer.sql_text.strip():
            findings.append("sql_text is required.")
        if not answer.table_result.columns:
            findings.append("table_result.columns is required.")
    if not answer.trace_id.strip():
        findings.append("trace_id is required.")
    return tuple(findings)
```

### 6.5 `VerifierAgentRunner`——用 `sql_text=None` 表示"不适用"

`VerifierAgentRunner._findings()`（已有逻辑，未改动）：`if self.sql_text is not None and not self.sql_text.strip(): findings.append("SQL text is missing.")`。编排器这一侧的调用点改动为：

```python
AgentName.VERIFIER: VerifierAgentRunner(
    verified=True,
    confidence=0.9,
    reason="Mock answer passes baseline verification.",
    sql_text=sql_candidate or None,  # 没有规划 SQL 时，"" 变成 None
),
```

### 6.6 `KnowledgePromotionService.promote_file()`——先检查，任何写入之前失败

```python
def promote_file(self, file_id: str, *, role: UserRoleV2, org_id: str) -> UserUploadedFile:
    _require_admin(role)
    file = self._repository.get(file_id)
    if file is None or file.org_id != org_id or file.file_type != "unstructured" or file.status != "ready":
        raise FileNotPromotableError(file_id)

    chunks_with_vectors = self._vector_source.chunks_with_vectors_for_file(file_id)
    if not chunks_with_vectors:
        raise FileNotPromotableError(file_id)

    # document_id 在这之后才会生成，所有写入操作（VectorStore、实时的
    # InMemoryKnowledgeStore、Postgres 的 knowledge.* 系列表、
    # repository.save）都只发生在这一行之后。
```

### 6.7 `runtime_query_result_record_from_response()`——跳过，而不是崩溃

```python
def runtime_query_result_record_from_response(*, trace_id, session_id, user_id, org_id=None, question, data):
    ...
    sql_text = data_mapping.get("sql_text")
    if not isinstance(sql_text, str) or not sql_text.strip():
        return None
    ...
    return RuntimeQueryResultRecord(..., sql_text=sql_text, ...)
```

两个调用点（`http.py` 里的 `chat_query_v2`，以及 `/api/v1/chat/query` 旁边那个处理函数）本来就把 `None` 返回值当成"没什么好存的"处理——这一节只是改变了"什么算没什么好存的"这个判定标准。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-052 | 一个命中 RAG 关键词、但没有命中数据域、图表、分析类关键词的问题，分类结果恰好是 `{TaskType.RAG_EXPLANATION}`——不包含 `TaskType.SQL_QUERY`。 |
| AC-FV10-053 | 一个既命中 RAG 关键词、又命中数据域关键词的问题（例如"为什么营收下滑了？"），分类结果是 `{TaskType.SQL_QUERY, TaskType.RAG_EXPLANATION}`，跟本 Spec 之前的行为一致。 |
| AC-FV10-054 | 仅用 `{TaskType.RAG_EXPLANATION}` 构建出的计划恰好有两个步骤——`(RAG, VERIFIER)`——RAG 步骤的 `depends_on` 等于 `()`，校验步骤的 `depends_on` 等于 `(AgentName.RAG,)`。 |
| AC-FV10-055 | 给定一个知识库里存有能回答某个纯文档问题的文档，`SimpleOrchestrator.answer()` 对该问题返回的 `QueryAnswer`，`sql_text == ""`、`table_result == TableResult(columns=(), rows=())`、`evidence_list` 非空且引用了该文档、`warnings == ()`（两个校验器都没有报出 `VERIFICATION_FAILED`）。 |
| AC-FV10-056 | 一个 `sql_text`/`table_result.columns` 为空、但 `evidence_list` 非空的回答，通过 `AnswerAssemblyVerifier.verify()` 时结果不变（没有新增警告，置信度不变）。 |
| AC-FV10-057 | 一个 `sql_text`/`table_result.columns` 为空、且 `evidence_list` 也为空的回答，依然会被 `AnswerAssemblyVerifier.verify()` 判定失败，警告消息里同时列出两个缺失字段，置信度被压到 0.5。 |
| AC-FV10-058 | 对一个状态为 `ready`、类型为 `unstructured`、组织匹配、但向量源里没有对应 chunk 的文件调用 `promote_file()`，会抛出 `FileNotPromotableError`；调用之后：`VectorStore` 里没有新文档，实时的 `InMemoryKnowledgeStore` 里没有新文档，该文件在仓库里的 `promoted_to_doc_id` 依然是 `None`。 |
| AC-FV10-059 | 对同类文件调用 `promote_file()`，如果它的向量源里确实有 chunk（本 Spec 之前就有的成功路径），行为不受影响：文件被成功提升，`promoted_to_doc_id` 被设置，且这份文档在同一进程里立刻可以通过 `InMemoryKnowledgeStore.retrieve()` 检索到。 |
| AC-FV10-060 | 对一个纯文档问题发起 `POST /api/v2/chat/query` 请求，返回 HTTP 200（不是 500）；如果配置了 `RuntimeQueryResultStore`，这次请求的 `trace_id` 不会有任何记录被保存。 |

## 8. 测试计划

### 8.1 单元测试——问题分类

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-153 | 单元 | `QuestionClassifier().classify("Explain what the onepager says about pricing.")` 返回 `frozenset({TaskType.RAG_EXPLANATION})`——不含 `TaskType.SQL_QUERY`（AC-FV10-052）。 |
| TC-FV10-154 | 单元 | `QuestionClassifier().classify("Why did revenue drop?")` 返回 `frozenset({TaskType.SQL_QUERY, TaskType.RAG_EXPLANATION})`（AC-FV10-053，回归）。 |

### 8.2 单元测试——执行计划构建

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-155 | 单元 | `ExecutionPlanBuilder().build(frozenset({TaskType.RAG_EXPLANATION}))` 产出 `plan.agents() == (AgentName.RAG, AgentName.VERIFIER)`，`plan.steps[0].depends_on == ()`，`plan.steps[1].depends_on == (AgentName.RAG,)`（AC-FV10-054）。 |

### 8.3 单元测试——答案校验

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-156 | 单元 | 一个 `sql_text`/`table_result` 为空、`evidence_list` 里有一条 `EvidenceItem` 的回答，通过 `AnswerAssemblyVerifier.verify()` 后结果不变：没有警告，置信度不变（AC-FV10-056）。 |
| TC-FV10-157 | 单元 | 一个 `sql_text`/`table_result` 为空、`evidence_list` 也为空的回答，依然校验失败，警告消息里同时包含 `"sql_text is required."` 和 `"table_result.columns is required."`，置信度为 `0.5`（AC-FV10-057）。 |

### 8.4 单元测试——知识库提升

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-158 | 单元 | 对一个状态为 ready、类型为 unstructured、但向量源为空的文件调用 `promote_file()`，抛出 `FileNotPromotableError`；调用之后 `VectorStore`、实时的 `InMemoryKnowledgeStore`、以及该文件的 `promoted_to_doc_id` 全部保持不变（AC-FV10-058）。 |
| TC-FV10-159 | 单元（回归） | 对同类文件、但预先种了一个 chunk 的情况调用 `promote_file()`，提升成功，且这份文档立刻能通过 `InMemoryKnowledgeStore.retrieve()` 检索到（AC-FV10-059）——已有测试，重新验证其不受本 Spec 改动影响。 |

### 8.5 编排器级测试——端到端的纯文档回答

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-160 | 编排器（集成） | 给定一个存有能回答该问题的文档的知识库，`SimpleOrchestrator.answer()` 对一个纯文档问题的回答，`sql_text == ""`、`table_result == TableResult(columns=(), rows=())`、有一条匹配的证据、`warnings == ()`、`confidence > 0.5`——这是抓出 FR-FV10-062（第 6.5 节）的那条测试：如果 `VerifierAgentRunner` 收到的是 `sql_text=""` 而不是 `None`，这条测试就会失败（AC-FV10-055）。 |

### 8.6 回归测试——已有 SQL/RAG 路径不受影响

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-161 | 回归 | 覆盖纯 SQL、图表、分析类、以及 SQL+RAG 组合问题的已有编排器测试（例如 `test_orchestrator_uses_knowledge_store_for_rag_evidence`、`test_orchestrator_attaches_chart_spec_for_kpi_query`），在本 Spec 的分类器/计划构建器/校验器改动落地之后，全部保持通过（NFR-FV10-021）。 |

### 8.7 HTTP 级测试——纯文档问题不会把接口打崩

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-162 | 集成（HTTP） | 对一个配置了 `RuntimeQueryResultStore` 的应用，用一个纯文档问题发起 `POST /api/v2/chat/query` 请求，返回 HTTP 200，且这次响应的 `trace_id` 在存储里没有对应记录——这是抓出 FR-FV10-063 的那条测试：如果 `runtime_query_result_record_from_response()` 依然去构造 `RuntimeQueryResultRecord(sql_text="")`，这条测试就会因为一个没被捕获的 500 而失败（AC-FV10-060）。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-057 | AC-FV10-052, AC-FV10-053 | TC-FV10-153, TC-FV10-154 |
| FR-FV10-058 | AC-FV10-054 | TC-FV10-155 |
| FR-FV10-059 | AC-FV10-055 | TC-FV10-160 |
| FR-FV10-060 | AC-FV10-056, AC-FV10-057 | TC-FV10-156, TC-FV10-157 |
| FR-FV10-061 | AC-FV10-058, AC-FV10-059 | TC-FV10-158, TC-FV10-159 |
| FR-FV10-062 | AC-FV10-055 | TC-FV10-160 |
| FR-FV10-063 | AC-FV10-060 | TC-FV10-162 |
| NFR-FV10-021 | AC-FV10-053 | TC-FV10-154, TC-FV10-161 |

## 10. 实现备注

- FR-FV10-057 里 `not is_rag` 这一句，是让本 Spec 的影响范围保持克制的关键：除了那种命中 RAG 关键词、又不命中其它任何信号的问题之外，SQL 依然是默认要走的。一个用了不在关键词表里的 RAG 相关表达、又没有数据域关键词、也没有其它信号的问题，依然会照旧走 SQL——本 Spec 让"纯 RAG 路由"这件事变得可能，但不打算把分类器的关键词覆盖面做到穷尽。
- FR-FV10-062 不在最初的设计评审范围内——是在写 TC-FV10-160（一条编排器级、而不是单元级的测试）确认修复是否完整时才发现的。`AnswerAssemblyVerifier`（FR-FV10-060）和 `VerifierAgentRunner`（FR-FV10-062）是两个独立的校验器，检查的是两条看起来相似、实则不同的不变式；修好一个不代表另一个也修好了，而只覆盖其中一个的单元测试是抓不出这个问题的。这就是即便 TC-FV10-160 涉及的各项行为分别都有更窄的单元测试覆盖，依然要把它留在测试计划里的具体理由。
- FR-FV10-063 是往外再多走一层才发现的：FR-FV10-060 和 FR-FV10-062 都修完、TC-FV10-156/157/160 也都通过之后，对着真实跑起来的应用发一次真实的 HTTP 请求，依然返回 500。`RuntimeQueryResultRecord` 是第三个独立强制要求"SQL 文本必须存在"的地方，只有走到 `http.py` 里的响应序列化那一步才会碰到，`QueryAnswer` 的构造过程根本不经过它——本 Spec 测试套件里没有任何单元测试或编排器级测试会跑到那条代码路径。TC-FV10-162 特意选择做成一条 HTTP 级测试（用 `TestClient` 打 `create_app()`），而不是单独针对 `runtime_query_result_record_from_response()` 写一条更窄的单元测试，就是因为这个 bug 出在"一个响应信封是怎么被转成一条持久化记录的"这个环节上，不是出在某个函数签名上——单元测试的调用方完全可能"凑巧"传对参数从而漏过这个问题。
- FR-FV10-061 里"不得创建、更新或写入"这一句，特意点明了*具体是哪些地方*不能被写入（`VectorStore`、实时的 `InMemoryKnowledgeStore`、Postgres、`promoted_to_doc_id`），而不是笼统地说"必须失败"——原本那个 bug 的问题不在于提升操作没有报告成功，而在于它报告了成功、但同时写入了一个检索不到的半成品结果。一条只检查是否抛出异常、不检查是否留下部分写入的测试，是抓不出"退化回那种 bug 形态"这类回归的。
- 本 Spec 没有为 `_index_into_live_rag()`（设计文档第 6.6 节）里走 Postgres `knowledge_connection` 分支的部分单独新增测试用例，超出 FV10.1 已有测试套件已经覆盖的范围（`test_http_promoted_document_surfaces_in_evidence_for_the_promoting_user` 及相邻测试）——FR-FV10-061 的这道检查在到达那个分支之前就会先运行，所以本 Spec 不需要为它单独新增 Postgres 路径的测试。
