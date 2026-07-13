# 10.9 给文件分支相关性判断加一道业务数据信号安全网

## 1. 解决的问题

[10.8](08-question-relevance-gate-before-file-branch-routing.zh-CN.md) 第 6 节自己就说明了这道判断是启发式的，不是真正的理解：`question_references_attached_file()` 只能抓到问题跟文件列名/文件名之间字面上的词元重合。一个确实跟附带文件相关、但用词跟 schema 不一样的问题——比如用业务同义词 "territory" 指代实际列名是 `region` 的列，或者用 "order volume" 指代列名是 `orders` 的列——跟文件没有任何字面词元重合，会被误判为不相关，转去主编排器，而主编排器手上根本没有这份文件的数据，同样答不出来。本文档要关上的就是这个具体缺口：在相信一个"不相关"的判断结果之前，先用第二个独立信号去交叉验证一下，而不是只凭词元重合度就下结论。

## 2. 已经具备的基础

10.8 那道判断，已经接进了 `chat_query_v2()`：

```python
route_to_file_branch = bool(effective_file_ids) and question_references_any_attached_file(
    str(body["question"]), effective_files
)
```

另外，`QuestionClassifier`（`src/chatbi/orchestration/routing.py`）本来就已经存在，而且在同一条请求路径里已经在被用（`_handle_file_data_chat_query` 会调用 `question_classifier.classify(question)` 来决定要不要再叠加一层知识库 RAG 证据）。它的 `classify()` 方法内部会算出一个 `has_data_signal`，来自一份 `_DATA_DOMAIN_KEYWORDS` 关键词表——`revenue`、`order`、`orders`、`refund`、`active users`、`support`、`ticket`、`case volume`、`total`、`count`、`how many`、`average`、`sum`、`rate`——但这个中间变量是私有的，没有对外暴露，而且被并进了 `needs_sql` 这个综合判断里（`has_data_signal or is_chart or is_analytics or not is_rag`），它最终产出的 `TaskType.SQL_QUERY` 因为有 `or not is_rag` 这个兜底分支，几乎对任何问题都会是 True——单独拿这个结果来做本次要用的判断，几乎没有区分度。

## 3. 一次在正式动手写代码之前就被纠正的设计

这个修复最初的版本，是在动手实现之前先跟用户讲过的方案：用 `resolve_federated_pg_context()`（`business_table_catalog.py`）去交叉验证"不相关"这个判断——理由是：如果这个函数也找不到一张真实的业务表能对应这个问题，那大概率说明这个问题其实还是在问附带的文件，只是措辞不一样，这时候留在文件分支是更安全的默认选择。

但在正式写代码之前，先拿这次报告的 bug 本身那个问题去验证了一下，结果证明这个方案是反的。`resolve_federated_pg_context()` 的文档字符串写得很清楚，它自己的匹配规则是："Matches only if the question mentions the table's name（问题里必须直接提到表名，下划线或空格分隔均可）。"报告里的原始问题"Compare total ticket count by product in H1 2026."，从头到尾都没有出现字面上的 `support_ticket_summary` 或 "support ticket summary"——所以这个函数对这个问题也会返回 `None`，跟它面对一个真正跟任何业务表都无关的问题时返回的结果一模一样。如果拿"联邦查询也匹配不到表"来触发安全网，就意味着：对 10.8 本来就是为了修复的*这个具体案例*，安全网反而会被触发，把请求拉回文件分支——悄悄撤销了 10.8 自己为了修这个 bug 而做的修复。

这个错误的根源，是把两个不同的问题混为一谈了："有没有一张真实的业务表可以拿这份文件去联表查询"（范围很窄，靠字面表名匹配，这是 `resolve_federated_pg_context` 实际在检查的东西），跟"这个问题本身读起来像不像一个真实的业务数据问题，跟任何文件都无关"（范围更宽，这才是这里真正需要的判断）。`QuestionClassifier._DATA_DOMAIN_KEYWORDS` 本来就是在回答第二个问题——它早就在代码库里了，只是没有被单独暴露成一个可以直接调用的检查。

## 4. 设计：把范围更窄的那个信号单独暴露出来，而不是用那个综合信号

`QuestionClassifier` 新增了一个公开方法，直接读取那份已有的关键词表，不经过 `classify()` 那个范围更宽、几乎总是为真的综合判断：

```python
def has_data_domain_signal(self, question: str) -> bool:
    return self._contains_any(question.strip().lower(), self._DATA_DOMAIN_KEYWORDS)
```

`chat_query_v2()` 里的路由判断现在把它当作一道交叉验证，只在 10.8 那道词元重合度判断已经说"不相关"的时候才会用到：

```python
if not route_to_file_branch and effective_files and not question_classifier.has_data_domain_signal(
    str(body["question"])
):
    route_to_file_branch = True
```

写成决策表更直观：

| 词元重合度判断 | 是否命中业务数据关键词 | 结果 |
|---|---|---|
| 相关 | —— | 走文件分支（跟 10.8 保持一致，没变） |
| 不相关 | 是 | 走主编排器——有交叉验证支撑：这个问题本身读起来就是一个真实的业务数据问题，跟这份文件无关 |
| 不相关 | 否 | 走文件分支（判断结果被覆盖）——两边都没找到别的地方能接住这个问题，与其瞎猜主编排器能答得更好，不如相信文件分支自己那个能看到真实 schema 的 LLM |

对于报告里那个 bug（"...ticket count by product..."），`has_data_domain_signal` 是 `True`（"ticket"、"total"、"count" 都命中了）——安全网不会触发，10.8 的修复依然按原计划正确地路由离开文件分支。而对于一个用同义词措辞、确实跟文件相关的问题（"Please describe my figures for this cycle."），既没有命中任何业务数据关键词，也没有跟 schema 有任何字面重合——安全网会触发，把请求留在文件分支。

## 5. 验证

新增的单元测试（`tests/test_agent_orchestration_routing.py`）直接覆盖 `has_data_domain_signal`：对报告里那个 bug 的原始问题返回 `True`，对一个含糊、不含任何业务词汇的问题（"How's it looking overall?"）返回 `False`。

新增的 HTTP 层测试（`tests/test_chat_query_with_files.py::test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`）附带一份有 `month`/`revenue` 列的文件，问"Please describe my numbers for this cycle."——跟 schema 或文件名没有任何字面重合，也没有命中任何业务数据关键词——断言 `table_result_source == "file"`，证明安全网把它留在了文件分支。10.8 原有的那个回归测试（报告里那个 bug 本身的问题，断言 `table_result_source is None`）依然照常通过，没有变化，证明安全网没有把原来那个洞重新捅开。

在重新构建的 Docker 镜像上，用真实的 OpenAI LLM client，按 10.8 验证时用的同一套 session 结构做了实盘复现：

- 报告里那个原始问题依然返回 `table_result_source: None`，正确地从 `business.support_ticket_summary` 计算出了答案。
- "Please describe my figures for this cycle."，针对真实的 `regional_sales_h1_2026.csv` 文件问出（跟 schema 没有任何字面重合），返回了 `table_result_source: "file"`，答案是从文件的真实数据行里正确计算出来的。

1360 个不需要连真实 Postgres、也不需要构建好的前端包的测试全部通过；跟本次改动无关的既有失败，数量和具体项都跟 10.8 自己验证时完全一致，没有变化。

## 6. 已知限制——本次没有解决

- **依然是一份关键词表，不是真正的理解。**`_DATA_DOMAIN_KEYWORDS` 是一份固定的、只支持英文、需要手工维护的词表。一个用词表之外的词汇表述出来的业务数据问题，同时又恰好跟附带文件的 schema 没有任何字面重合，依然会落到安全网的默认结果——按第 4 节的决策表，这意味着留在文件分支，而不是转去主编排器。这个默认值是刻意选的（第 4 节："与其瞎猜，不如相信文件分支自己那个能看到真实 schema 的 LLM"），但这意味着本次修复只是缩小了 10.8 原本留下的那个洞，并没有彻底关上 10.8 第 6 节最初指出的那一整类"用词不匹配"问题——它只关上了那些恰好能被 `_DATA_DOMAIN_KEYWORDS` 提供交叉验证信号的具体情形。
- **10.8 第 6 节指出的另外两个缺口依然留着。**混选结构化+非结构化文件时按单个文件做相关性过滤，以及 `FileDataAgent` 看不到列的实际存储取值格式，这两个都跟本次修复无关，各自有独立的前瞻性设计文档覆盖（[10.10](10-per-file-relevance-filtering-in-mixed-selections.zh-CN.md)、[10.11](11-value-sample-aware-schema-context.zh-CN.md)）。

## 7. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-077 | `QuestionClassifier` 必须暴露一个独立的 `has_data_domain_signal(question)` 检查，只读取它的 `_DATA_DOMAIN_KEYWORDS` 关键词表，跟 `classify()` 那个范围更宽、几乎总是为真的 `TaskType.SQL_QUERY` 综合判断相互独立。 | 已实现 |
| NFR-FV10-026 | 当文件分支相关性判断（10.8）判定某个问题跟所有附带文件都"不相关"时，在真正把路由决策改成"离开文件分支"之前，必须先用 `QuestionClassifier.has_data_domain_signal()` 做一次交叉验证；如果没有这个交叉验证信号支撑，请求必须留在文件分支。 | 已实现 |

## 8. 现状：已修复并验证

这次修复最初提出的设计，在写任何代码之前，就先拿报告里那个 bug 本身的问题去验证了一遍，结果发现对那个具体案例是反着的，于是改用 `QuestionClassifier` 已有的关键词信号，而不是 `resolve_federated_pg_context()`——这跟本项目 SDD+TDD 惯例本来就是为了在合并之前暴露出来的那类修正是同一种性质，只是这次提前到了设计评审阶段，而不是等到跑测试之后才发现。修复涉及 `src/chatbi/orchestration/routing.py` 和 `src/chatbi/api/http.py`；`tests/test_agent_orchestration_routing.py` 和 `tests/test_chat_query_with_files.py` 里新增了对应测试；按第 5 节所述，在重新构建的 Docker 镜像上、用真实 LLM provider 做了端到端验证。这份设计之后被写成了 [Spec FV10.9](../../../../spec/final-version/zh-CN/10-followups/09-data-domain-signal-safety-net-for-the-relevance-gate.spec.zh-CN.md)，转化成了正式的"必须"型需求、验收标准，以及一份直接对应上面这些真实测试名称的可追溯性矩阵——这里是先实现、后补 Spec，跟 Spec FV10.6 那种先写 Spec 再实现的顺序不一样，因为这个修复本身就是用 Spec FV10.5 那两个缺陷同样的实盘复现方式发现并修复的。
