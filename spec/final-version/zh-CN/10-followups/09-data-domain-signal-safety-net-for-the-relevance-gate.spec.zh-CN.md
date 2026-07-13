# Spec FV10.9：给文件分支相关性判断加一道业务数据信号安全网

来源设计文档：
- [10.9 给文件分支相关性判断加一道业务数据信号安全网设计](../../../../system_design/final-version/zh-CN/10-followups/09-data-domain-signal-safety-net-for-the-relevance-gate.zh-CN.md)
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；本 Spec 修订 `QuestionClassifier` 和 `chat_query_v2()` 的文件分支路由决策）

本 Spec 依赖的那道父级路由判断——[10.8 路由进文件分支之前，加一道问题相关性判断](../../../../system_design/final-version/zh-CN/10-followups/08-question-relevance-gate-before-file-branch-routing.zh-CN.md)（`src/chatbi/agents/file_query_support.py` 里的 `question_references_any_attached_file()`）——本身没有单独的 Spec，它是直接从设计文档实现的，跟 Spec FV10.5 那两个修复的做法一样。本 Spec 把 10.8 那道判断当作一个已经存在、已经测试过的依赖（见 `tests/test_chat_query_with_files.py` 和 `tests/test_file_query_support.py`），只对在它之上新增的这道安全网提出规格要求。

---

## 1. 目的

10.8 那道判断，只要问题跟附带文件的列名/文件名没有任何字面词元重合，就判定"不相关"。这对"这个用词跟 schema 对不上"来说是个有效信号，但并不能证明主编排器那边真的有一张业务表可以接住这个问题——一个用业务同义词表述、但文件 schema 里没有字面出现过的问题（比如用 "territory" 指代一个实际列名是 `region` 的列），会被错误地从一份它确实相关的文件那里路由走，而路由过去的地方同样答不出来。

本 Spec 加了第二道独立检查：在真正采纳"不相关"这个判断结果之前，先确认这个问题本身、独立于任何文件，读起来是不是真的像一个业务数据问题——用的是 `QuestionClassifier` 已有的 `_DATA_DOMAIN_KEYWORDS` 关键词表，通过一个新的独立方法暴露出来。如果没有这个交叉验证信号支撑，请求就留在文件分支，而不是被路由到一个同样大概率答不出来的地方。

## 2. 范围

**纳入范围：**
- 新增 `QuestionClassifier.has_data_domain_signal(question)` 方法，只读取已有的 `_DATA_DOMAIN_KEYWORDS` 关键词表，跟 `classify()` 那个范围更宽的 `TaskType.SQL_QUERY` 计算相互独立。
- 把这个方法接入 `chat_query_v2()` 的文件分支路由决策，作为一道交叉验证——只在 10.8 那道判断已经判定"请求附带的文件跟问题不相关"时才会被评估。

**不纳入范围：**
- 对 10.8 的 `question_references_any_attached_file()`/`question_references_attached_file()` 判断函数本身的任何改动——本 Spec 只是在它们的判断结果之后，加了第二道独立检查。
- 对 `QuestionClassifier.classify()` 自己的 `TaskType.SQL_QUERY`/`needs_sql` 计算的任何改动——本 Spec 直接读取 `_DATA_DOMAIN_KEYWORDS`，不经过那个综合判断。
- 混选结构化/非结构化文件时按单个文件做相关性过滤，以及让 `FileDataAgent` 能看到列的实际存储取值格式——这两个都是独立的、尚未实现的提议（见 [10.10](../../../../system_design/final-version/zh-CN/10-followups/10-per-file-relevance-filtering-in-mixed-selections.zh-CN.md) 和 [10.11](../../../../system_design/final-version/zh-CN/10-followups/11-value-sample-aware-schema-context.zh-CN.md)）。

## 3. 参与方

沿用父 Spec FV-10 第 3 节定义的参与方。不引入新参与方。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-077 | `QuestionClassifier` 必须暴露一个公开方法 `has_data_domain_signal(question: str) -> bool`，当且仅当 `question`（忽略大小写）里包含至少一个 `_DATA_DOMAIN_KEYWORDS` 里的字面关键词时返回 `True`，且这个判断必须独立于 `classify()` 的 `needs_sql`/`TaskType.SQL_QUERY` 计算。 |
| NFR-FV10-026 | 当 `chat_query_v2()` 的文件分支路由决策（10.8 的 `question_references_any_attached_file()`）判定"请求附带的文件跟问题不相关"时，在真正把请求路由离开文件分支之前，必须先调用 `question_classifier.has_data_domain_signal(question)` 做交叉验证。如果这次调用也返回 `False`，请求必须路由进文件分支，而不是主编排器。当 10.8 那道判断已经判定"相关"时，这道交叉验证检查不得运行，也不得产生任何影响。 |

## 5. 非功能需求

除上面的 NFR-FV10-026 外没有其他条目——那一条本身就是对"交叉验证检查*何时*可以运行"这件事的非功能性约束，本 Spec 不再单列一份独立于它的非功能需求。

## 6. 数据契约

### 6.1 `QuestionClassifier.has_data_domain_signal()` —— `src/chatbi/orchestration/routing.py`

```python
def has_data_domain_signal(self, question: str) -> bool:
    return self._contains_any(question.strip().lower(), self._DATA_DOMAIN_KEYWORDS)
```

复用的是已有的 `_DATA_DOMAIN_KEYWORDS` 元组（`"revenue"`、`"order"`、`"orders"`、`"refund"`、`"active users"`、`"support"`、`"ticket"`、`"case volume"`、`"total"`、`"count"`、`"how many"`、`"average"`、`"sum"`、`"rate"`）和已有的 `_contains_any()` 辅助方法——这两个本来就在这个类里，供 `classify()` 自己使用；没有新增关键词表，也没有新写一套子串匹配逻辑。

### 6.2 `chat_query_v2()` 路由判断 —— `src/chatbi/api/http.py`

```python
route_to_file_branch = bool(effective_file_ids) and question_references_any_attached_file(
    str(body["question"]), effective_files
)
if not route_to_file_branch and effective_files and not question_classifier.has_data_domain_signal(
    str(body["question"])
):
    route_to_file_branch = True
if route_to_file_branch:
    ...  # 文件分支，未变
else:
    ...  # 主编排器分支，未变
```

交叉验证那条 `if` 是靠 `not route_to_file_branch` 做门禁的——当 10.8 那道判断已经返回 `True` 时，这段代码在结构上根本不可达；`effective_files` 在 `effective_file_ids` 为空（完全没有附带文件）时也是空的，同样会让这个条件在结构上为 `False`。这两点都是 NFR-FV10-026"不得运行"这句话的支撑依据，详见第 10 节。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-069 | `QuestionClassifier().has_data_domain_signal(question)` 对一个包含 `_DATA_DOMAIN_KEYWORDS` 字面匹配的问题（比如 `"Compare total ticket count by product in H1 2026."`，里面有 `"ticket"`、`"total"`、`"count"`）返回 `True`。 |
| AC-FV10-070 | `QuestionClassifier().has_data_domain_signal(question)` 对一个不包含任何 `_DATA_DOMAIN_KEYWORDS` 匹配的问题（比如 `"How's it looking overall?"`）返回 `False`。 |
| AC-FV10-071 | 一次带单个结构化文件附件的对话请求，如果这份文件的 schema/文件名跟问题没有任何词元重合（10.8 那道判断说"不相关"），而且这个问题包含 `_DATA_DOMAIN_KEYWORDS` 匹配，最终回答的 `table_result_source` 应该等于 `None`——是主编排器在回答，不是文件分支。 |
| AC-FV10-072 | 一次带单个结构化文件附件的对话请求，如果这份文件的 schema/文件名跟问题没有任何词元重合（10.8 那道判断说"不相关"），而且这个问题不包含任何 `_DATA_DOMAIN_KEYWORDS` 匹配，最终回答的 `table_result_source` 应该等于 `"file"`——请求留在了文件分支。 |
| AC-FV10-073 | 一次对话请求，如果它附带的文件已经被 10.8 那道判断判定为"相关"（不管是因为有字面词元重合，还是因为附带的文件里有非结构化的），那么不管针对同一个问题 `has_data_domain_signal()` 会返回什么，最终回答都应该完全一样——本 Spec 新增的交叉验证检查对这类请求不应该产生任何可观察的影响。 |
| AC-FV10-074 | 一次完全没有 `file_ids`、也没有 session 继承的文件选择的对话请求，应该继续路由到主编排器，不受本 Spec 影响。 |

## 8. 测试计划

### 8.1 单元测试——`has_data_domain_signal()`

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-178 | 单元 | `QuestionClassifier().has_data_domain_signal("Compare total ticket count by product in H1 2026.")` 返回 `True`（AC-FV10-069）。对应实现：`tests/test_agent_orchestration_routing.py::test_has_data_domain_signal_true_for_the_reported_bug_question`。 |
| TC-FV10-179 | 单元 | `QuestionClassifier().has_data_domain_signal("How's it looking overall?")` 返回 `False`（AC-FV10-070）。对应实现：`tests/test_agent_orchestration_routing.py::test_has_data_domain_signal_false_for_a_vague_question_with_no_business_vocabulary`。 |

### 8.2 集成测试——HTTP 路由

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-180 | 集成（HTTP） | `POST /api/v2/chat/query`，带一个结构化文件附件（`month`/`revenue` 列），问题是 `"Compare total ticket count by product in H1 2026."`，返回 `200`，`data.table_result_source == None`（AC-FV10-071）。对应实现：`tests/test_chat_query_with_files.py::test_chat_query_with_a_structured_file_irrelevant_to_the_question_routes_to_main_orchestrator`。 |
| TC-FV10-181 | 集成（HTTP） | `POST /api/v2/chat/query`，带同一份结构化文件附件，问题是 `"Please describe my numbers for this cycle."`（跟 schema/文件名没有重合，也不含任何 `_DATA_DOMAIN_KEYWORDS` 匹配），返回 `200`，`data.table_result_source == "file"`（AC-FV10-072）。对应实现：`tests/test_chat_query_with_files.py::test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`。 |

### 8.3 回归测试——交叉验证不改变"已相关"或"完全无文件"的请求

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-182 | 回归 | `tests/test_chat_query_with_files.py`、`tests/test_chat_query_federated.py`、`tests/test_chat_query_file_rag_analytics.py`、`tests/test_multi_turn_conversation.py` 里所有被 10.8 那道判断判定为"相关"的既有测试（比如 `test_chat_query_with_valid_file_ids_returns_file_sourced_table_result`、`test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both`、`test_third_turn_inherits_the_second_turns_explicit_file_not_the_first`），在本 Spec 的改动之后依然照常通过，没有变化（AC-FV10-073）。除了重新跑一遍既有测试套件之外，不为这条标准单独新增测试——原因见第 10 节：这是一个代码结构上的保证，不是本 Spec 新代码会在运行时真正走到的分支。 |
| TC-FV10-183 | 回归 | `tests/test_chat_query_with_files.py::test_chat_query_without_file_ids_is_unaffected` 和 `tests/test_multi_turn_conversation.py::test_a_first_ever_question_with_empty_file_ids_uses_the_main_orchestrator` 依然照常通过，没有变化（AC-FV10-074）。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-077 | AC-FV10-069, AC-FV10-070 | TC-FV10-178, TC-FV10-179 |
| NFR-FV10-026 | AC-FV10-071, AC-FV10-072, AC-FV10-073, AC-FV10-074 | TC-FV10-180, TC-FV10-181, TC-FV10-182, TC-FV10-183 |

## 10. 实现备注

- AC-FV10-073 没有专门新增运行时测试用例，原因跟 Spec FV10.6 的 FR-FV10-069 是一样的（见那份 Spec 自己的第 10 节）：这是一个结构性保证，不是本 Spec 新代码会在运行时真正走到的分支。`if not route_to_file_branch and effective_files and not question_classifier.has_data_domain_signal(...)` 这行代码，靠 Python 的 `and` 短路特性，在 `route_to_file_branch` 已经是 `True` 的时候根本不会去调用 `has_data_domain_signal()`——交叉验证检查在这种情况下是不可达的，不只是"观察到没有影响"而已。TC-FV10-182 重新跑一遍既有测试套件作为回归检查，正是出于这个原因，跟 Spec FV10.6 自己的 AC-FV10-068"通过代码结构验证"扮演的是同一个角色。
- 本 Spec 自己的设计过程，值得原原本本记录下来，因为它跟 Spec FV10.5、FV10.6 发现缺陷的方式不一样：最初为 NFR-FV10-026 考虑的方案——用 `resolve_federated_pg_context()`（`business_table_catalog.py`）而不是 `has_data_domain_signal()` 来交叉验证"不相关"的判断结果——在*任何代码写出来之前*，就先拿 AC-FV10-071 里那个具体的验收场景去检查过一遍，结果发现对那个问题它也会返回 `None`（它只在问题里字面提到一张业务表的名字时才会匹配，比如 `"support_ticket_summary"`，而 `"Compare total ticket count by product in H1 2026."` 从来没有）。如果真的拿它当交叉验证信号，AC-FV10-071 会失败，不会通过——这道交叉验证会在本 Spec 明确要求"不得被重新路由回文件分支"的这个具体请求上被触发。来源设计文档的第 3 节完整记录了这次修正；本 Spec 的 FR-FV10-077/NFR-FV10-026 反映的是修正之后的设计，不是最初考虑的那一版。
- `_DATA_DOMAIN_KEYWORDS` 是复用，不是复制：`has_data_domain_signal()` 读取的，跟 `classify()` 自己算 `has_data_signal` 中间值时读取的（见 Spec FV10.5 第 6.1 节），是同一份私有元组。本 Spec 不会新增、删除或调整这份列表里的任何一个关键词——将来如果为了 Spec FV10.5 的目的调整了 `_DATA_DOMAIN_KEYWORDS`，本 Spec 的交叉验证信号也会自动跟着变，这是刻意的：两处用法背后问的其实是同一个问题——"这读起来像不像一个真实的业务数据问题"。
