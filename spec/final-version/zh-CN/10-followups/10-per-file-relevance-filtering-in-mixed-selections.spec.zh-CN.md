# Spec FV10.10：混选场景下按单个文件做相关性过滤

来源设计文档：
- [10.10 混选场景下按单个文件做相关性过滤设计](../../../../system_design/final-version/zh-CN/10-followups/10-per-file-relevance-filtering-in-mixed-selections.zh-CN.md)
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；本 Spec 修订 `_handle_file_data_chat_query`）
- [Spec FV10.6：混选结构化/非结构化文件时的混合回答](06-hybrid-file-answering-for-mixed-selections.spec.zh-CN.md)（本 Spec 在 FR-FV10-064 的结构化/非结构化拆分之内，收窄了其中一种具体情形——见第 4 节 FR-FV10-078——且不改变那份 Spec FR-FV10-064 到 FR-FV10-070 建立的任何其他行为）
- [Spec FV10.9：给文件分支相关性判断加一道业务数据信号安全网](09-data-domain-signal-safety-net-for-the-relevance-gate.spec.zh-CN.md)（本 Spec 第 10 节记录了实现过程中，跟 FV10.9 自身行为之间一次真实的交互问题——测试套件抓出来的——见 FR-FV10-083）

本 Spec 的前置依赖——10.8 那道请求级别的相关性判断（`src/chatbi/agents/file_query_support.py` 里的 `question_references_any_attached_file()` / `question_references_attached_file()`）——已经实现（只有设计文档，没有单独的 Spec，见 Spec FV10.9 自己开头的同一条说明）。本 Spec 原样复用 `question_references_attached_file()`，只是把它用在一个不同的调用点上——本 Spec 不引入任何新的相关性判断逻辑。

---

## 1. 目的

Spec FV10.6（第 4 节 FR-FV10-064）本来就会在决定怎么回答之前，先把请求的 `file_ids` 拆成结构化子集和非结构化子集。本 Spec 依赖的 10.8 那道判断，决定的是整个请求要不要进入 `_handle_file_data_chat_query`——但一旦进去了，此前没有任何机制像请求级别那道判断的聚合逻辑那样，再对*结构化*子集按相关性做一次过滤。一个混选场景——附带的一份结构化文件跟问题无关，附带的一份非结构化文件跟问题相关——依然会把那份不相关的结构化文件交给 `FileDataAgent`/`FederatedQueryAgent`，而它们没有任何"这不是在问你的数据"这种优雅的输出——这正是 10.8 在请求层面修好的那个失败模式，在 10.8 自己那个聚合 `any(...)` 判断覆盖不到的、范围更窄的混选场景下，又能被重新触发一次。

本 Spec 定义的修复是：在 `resolve_federated_pg_context()` 或 `FileDataAgent`/`FederatedQueryAgent` 看到 `structured_ids`（Spec FV10.6 自己的产出）之前，先把它过滤成只剩 `question_references_attached_file()` 判断为相关的那些文件——但只在确实存在一个非结构化替代方案时才这么做（FR-FV10-083；这个条件存在的原因见第 10 节）。

## 2. 范围

**纳入范围：**
- 在 `_handle_file_data_chat_query` 内部，在 `pg_context` 解析之前、在两个 agent 运行之前，用已有的 `question_references_attached_file()` 判断函数，对 `structured_ids`（Spec FV10.6 的 `split_file_ids_by_type()` 产出）做过滤——只在 `unstructured_ids` 也非空时才生效。
- `unstructured_ids` 不受这个判断函数的过滤，保持原样。
- 保持 `effective_file_ids` 和 session 里存储的文件选择（`session_file_context`）完全跟 Spec FV10.4/10.8 现有产出一致——这道过滤不影响它运行所在的那一轮之外的任何一轮。

**不纳入范围：**
- 对 `question_references_attached_file()`/`question_references_any_attached_file()` 本身的任何改动（属于 Spec FV10.9 的范围，本 Spec 不受影响）。
- 对 `FileScopedRetriever` 自己针对 `unstructured_ids` 的相关性处理逻辑的任何改动（Spec FV10.6 第 6.2 节）——本 Spec 明确不对它做过滤，见 FR-FV10-079。
- 对 `resolve_federated_pg_context()` 自身业务表名匹配逻辑（`business_table_catalog.py`）的任何改动——本 Spec 只改变送到它面前的结构化文件集合，不改变它怎么决定要联表查哪张表。
- `FileDataAgent`/`FederatedQueryAgent` 拿到（可能被收窄过的）`structured_ids` 之后自己内部的行为——不变。

## 3. 参与方

沿用父 Spec FV-10 第 3 节定义的参与方。不引入新参与方。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-078 | `_handle_file_data_chat_query` 必须在 `split_file_ids_by_type()` 产出 `structured_ids`（Spec FV10.6 FR-FV10-064）之后、在调用 `resolve_federated_pg_context()` 之前，立刻把 `structured_ids` 过滤成只保留 `question_references_attached_file(question, files_by_id[fid])` 返回 `True` 的那些文件。如果过滤之后 `structured_ids` 变空，请求必须按 Spec FV10.6 自己"没有结构化文件"那条路径原样继续（`federated_output = None; file_output = None`，退回到纯证据回答，或者既有的 FR-FV10-066 错误路径）。 |
| FR-FV10-079 | 这道过滤不得应用到 `unstructured_ids` 上。哪些非结构化文件能贡献证据，必须只由 `FileScopedRetriever` 自己按单文件的相关性处理机制决定（Spec FV10.6 第 6.2 节——对不相关的文件返回空结果，不是报错）。 |
| FR-FV10-083 | 当 `unstructured_ids` 为空时，FR-FV10-078 的这道过滤完全不得运行——这种情况下 `structured_ids` 必须原样透传，不受本 Spec 过滤。一个纯结构化的选择，必须完全交给 Spec FV10.9 的请求级安全网去判断——那道安全网有可能刻意把请求留在文件分支，正是因为按本 Spec 的判断函数看，`structured_ids` 里没有一个相关的成员，同时也没有独立的业务数据信号。如果这种情况下依然应用本 Spec 的过滤，就会在 FV10.9 决定保留 `structured_ids` 之后的下一层调用里，悄悄把它重新清空，把那次决定撤销掉。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-027 | 对于一个附带的结构化文件全都已经通过 `question_references_attached_file()` 的请求，这道过滤产出的 `structured_ids` 必须跟 Spec FV10.6 未过滤时的输出完全一致（成员相同、顺序相同）——本 Spec 不得改变这种情况下的行为。这道过滤不得修改 `effective_file_ids`，也不得修改任何一轮的 session 存储文件选择（`session_file_context`）——从某一轮过滤后的 `structured_ids` 里被剔除的文件，必须依然对之后一轮自己的过滤判断保持可用、不受本 Spec 影响。 |

## 6. 数据契约

### 6.1 `_handle_file_data_chat_query` —— 过滤后的 `structured_ids`

```python
files_by_id: dict[str, UserUploadedFile] = {...}  # 不变（Spec FV10.6）
structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, files_by_id)

# FR-FV10-078/083：按单个文件做相关性过滤，原样复用 Spec FV10.9
# 依赖的 question_references_attached_file()。只在 unstructured_ids
# 也非空时生效（FR-FV10-083）——这个条件为什么是硬性要求、不是可选
# 项，见第 10 节。
if unstructured_ids:
    structured_ids = tuple(
        fid for fid in structured_ids
        if question_references_attached_file(question, files_by_id[fid])
    )

pg_context = (
    resolve_federated_pg_context(question, role, active_business_table_catalog)
    if active_business_table_catalog is not None and structured_ids
    else None
)
```

从 `pg_context` 往后的所有逻辑，都是 Spec FV10.6 自己那套没有改动过的控制流（`06-hybrid-file-answering-for-mixed-selections.spec.zh-CN.md` 第 6.5 节）——本 Spec 唯一的改动，就是在那套控制流开始之前，加上这道由 `if unstructured_ids:` 门禁保护的过滤。`question_references_attached_file`——从 `chatbi.agents.file_query_support` 导出，也通过 `chatbi.agents.__init__` 以 `question_references_any_attached_file` 的姊妹身份重新导出——已经导入到 `http.py` 现有的 `from chatbi.agents import (...)` 语句块里。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-075 | 一次请求，`file_ids` = [一份跟问题相关的结构化文件、一份跟问题不相关的结构化文件、一份跟问题相关的非结构化文件]，产出的 `table_result` 应该只反映那份相关结构化文件的数据，而且发给 LLM 的 SQL 生成 prompt 的 schema 上下文字符串里，绝不应该出现那份不相关结构化文件的 `file_id`。 |
| AC-FV10-076 | 一次请求，`file_ids` = [一份跟问题不相关的结构化文件、一份跟问题相关的非结构化文件]，产出的 `table_result_source` 应该等于 `None`，`evidence_list` 里应该包含那份非结构化文件的证据，而且 `task_type` 为 `"file_data_sql_generation"` 或 `"federated_query_sql_generation"` 的 LLM 调用次数应该是零。 |
| AC-FV10-077 | 一次请求，`file_ids` = [一份跟问题不相关的结构化文件、一份内容也跟问题不相关的非结构化文件]，应该以 Spec FV10.6 FR-FV10-066 已经会产出的那种"两个子集都没查到能回答的东西"的 `error.message` 失败——本 Spec 不改变这一点。 |
| AC-FV10-078 | 一次请求，`file_ids` = [一份跟问题相关的结构化文件、一份跟问题相关的非结构化文件]（就是 Spec FV10.6 自己的 `test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both` 场景），产出的响应应该跟同一个请求在没有应用本 Spec 改动的版本上跑出来的响应逐字节一致。 |
| AC-FV10-079 | 给定一个两轮的 session：第一轮附带一份跟第一轮问题不相关的结构化文件（会被本 Spec 从第一轮的 `structured_ids` 里过滤掉），同时附带一份相关的非结构化文件；第二轮不显式传 `file_ids`（继承 session 里存的选择），问一个跟那份结构化文件相关的问题——第二轮的 `table_result` 应该反映那份结构化文件的数据——证明本 Spec 对第一轮的过滤效果，没有渗透进第二轮的 `effective_file_ids` 或 session 存储的选择里。 |
| AC-FV10-088 | 一次请求，`file_ids` = [只有一份结构化文件，用了 schema 里没有字面出现过的词汇表述，也没有任何独立的业务数据关键词信号]（Spec FV10.9 自己触发问题的那个场景），应该由文件分支回答（`table_result_source` 等于 `"file"`）——对于没有附带任何非结构化文件的请求，本 Spec 的过滤不得运行，也不得撤销 Spec FV10.9 的安全网。 |

## 8. 测试计划

### 8.1 集成测试——HTTP，混选场景过滤

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-184 | 集成（HTTP） | `POST /api/v2/chat/query`，`file_ids` = [相关结构化、不相关结构化、相关非结构化]，用一个会记录调用内容的假 LLM client 承接文件分支的 SQL 生成调用：断言记录下来的 system prompt 的 schema 上下文字符串里，包含那份相关结构化文件的 `file_id`，不包含不相关那份的；同时断言 `table_result` 只匹配相关文件的种子数据（AC-FV10-075）。那份不相关文件刻意没有写任何 Parquet 快照——如果过滤退化成依然去查询它，这条测试会因为存储查找失败而报错，而不是悄悄断言错了。对应实现：`tests/test_chat_query_with_files.py::test_mixed_selection_with_an_irrelevant_structured_file_excludes_it_from_sql_generation`。 |
| TC-FV10-185 | 集成（HTTP） | `POST /api/v2/chat/query`，`file_ids` = [不相关结构化、相关非结构化]，用一个会记录调用内容的假 LLM client：断言记录下来的调用列表里，没有任何一条 `task_type` 属于 `{"file_data_sql_generation", "federated_query_sql_generation"}`，`table_result_source` 是 `None`，`evidence_list` 里包含那份非结构化文件的证据（AC-FV10-076）。对应实现：`tests/test_chat_query_with_files.py::test_mixed_selection_with_only_irrelevant_structured_files_skips_sql_generation_entirely`。 |
| TC-FV10-186 | 集成（HTTP） | `POST /api/v2/chat/query`，`file_ids` = [不相关结构化、内容也不相关的非结构化]，返回的 `error.message` 文字应该跟 Spec FV10.6 自己的 `test_chat_query_with_only_an_unstructured_file_with_irrelevant_content_returns_400` 产出的一致（AC-FV10-077）。对应实现：`tests/test_chat_query_with_files.py::test_mixed_selection_with_nothing_relevant_returns_the_pre_existing_unanswerable_error`。 |

### 8.2 回归测试——已相关的混选场景不受影响

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-187 | 回归 | 在应用了本 Spec 这道过滤的版本上，原样重新跑一遍 Spec FV10.6 现有的 `tests/test_chat_query_with_files.py::test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both`，依然通过（AC-FV10-078、NFR-FV10-027）。 |

### 8.3 多轮集成测试——过滤效果不会渗透进 session 状态

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-188 | 集成（HTTP，多轮） | 两轮 session：第一轮发送 `file_ids` = [结构化文件 X（跟第一轮问题不相关）、非结构化文件 Y（相关）]；第二轮不发送 `file_ids`（继承 session 里存的选择，按 Spec FV10.4 依然包含 X），问一个跟 X 相关的问题。断言第二轮的 `table_result` 反映了 X 的种子数据——证明本 Spec 按轮次做的 `structured_ids` 过滤，没有动到 `effective_file_ids`/`session_file_context`（AC-FV10-079）。对应实现：`tests/test_chat_query_with_files.py::test_a_structured_file_filtered_out_of_one_turn_remains_available_to_a_later_relevant_turn`。 |

### 8.4 回归测试——Spec FV10.9 的安全网不受影响

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-197 | 回归 | Spec FV10.9 现有的 `tests/test_chat_query_with_files.py::test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`（只附带单份结构化文件，没有非结构化文件）在应用了本 Spec 这道过滤的版本上依然照常通过，没有变化（AC-FV10-088、FR-FV10-083）。这条测试在本 Spec 的过滤最初被写成不带 `if unstructured_ids:` 门禁时曾经回归过——见第 10 节。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-078 | AC-FV10-075, AC-FV10-076, AC-FV10-077 | TC-FV10-184, TC-FV10-185, TC-FV10-186 |
| FR-FV10-079 | AC-FV10-076 | TC-FV10-185 |
| FR-FV10-083 | AC-FV10-088 | TC-FV10-197 |
| NFR-FV10-027 | AC-FV10-078, AC-FV10-079 | TC-FV10-187, TC-FV10-188 |

## 10. 实现备注

- FR-FV10-083 和 TC-FV10-197 都不属于本 Spec 最初的版本。按照开头 SDD+TDD 的指导，TC-FV10-184 到 TC-FV10-188 是先写出来的，先确认它们针对未过滤的代码、因为预期的原因失败，然后才实现了 FR-FV10-078 的过滤——当时还没有现在第 6.1 节里那道 `if unstructured_ids:` 门禁。紧接着跑了一遍*全量*测试套件——不只是这五条新测试——立刻回归了 Spec FV10.9 的 `test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`：一份单独的结构化文件，用了 schema 里没有字面出现过的词汇，也没有独立的业务数据信号——这正是 FV10.9 的安全网存在的意义所在，就是要把这种请求留在文件分支。无条件的过滤重新跑了一遍 FV10.9 的安全网已经在请求层面覆盖过的同一个 `question_references_attached_file()` 判断，在下一层调用里悄悄把 `structured_ids` 重新清空，把那次覆盖撤销了。FR-FV10-083 和 TC-FV10-197 记录的就是这次修复，以及能再次抓住这个问题的回归测试；两者都是修正之后才加进本 Spec 的，不是最初版本就预见到的。
- 这跟 Spec FV10.9 自己第 10 节记录的那类修正是同一种性质（一份设计拿真实情况一检查，发现是错的），只是在整个流程里晚了一步才被抓到：FV10.9 的修正发生在任何代码写出来之前，靠的是拿一份提议的设计去对照报告里那个 bug 的真实问题；本 Spec 的修正发生在代码和新测试都已经写好之后，靠的是跑*既有的*回归测试套件。两者都是本项目 SDD+TDD 惯例在发挥作用的例子——差别只在于检查发生得多早，不在于检查有没有发生。
- AC-FV10-075 的断言检查的是那份不相关文件的 `file_id` 本身，而不是完整的 `file_{file_id}(...)` schema 那一整行字符串，因为 `FileDataAgent.build_schema_context()` 具体的渲染格式属于 Spec FV10.11（提议中，尚未实现）关心的范畴——本 Spec 只依赖"那个方法当前渲染出来的内容里，有没有出现这个 `file_id` 子串"，不依赖它列举列名的具体格式。
- 本 Spec 的测试计划里，没有任何一条测试直接演练"`FederatedQueryAgent` 的联表路径遇到被过滤过的 `structured_ids`"这种情况——Spec FV10.6 自己的联邦查询路径测试（`tests/test_chat_query_federated.py`）没有附带第二份不相关的结构化文件，本 Spec 也没有加——因为 `resolve_federated_pg_context()` 的行为不受"哪些结构化文件送到它面前"影响（来源设计文档第 5 节）——只受"到底还有没有结构化文件送到它面前"影响，而这一点已经被既有的 `and structured_ids` 判断覆盖，Spec FV10.6 也已经做过单元测试。
