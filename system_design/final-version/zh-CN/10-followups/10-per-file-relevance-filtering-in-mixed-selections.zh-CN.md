# 10.10 混选场景下按单个文件做相关性过滤

## 1. 解决的问题

[10.8](08-question-relevance-gate-before-file-branch-routing.zh-CN.md) 新增的 `question_references_any_attached_file()` 是一道路由层面的判断：只要附带的文件里没有一份跟问题相关，*整个*请求就不进文件分支。但这道判断是刻意做成按整个请求全有全无的，不是按单个文件的——只要附带的文件里*有任何一份*是非结构化的，`question_references_any_attached_file()` 就直接返回 `True`（请求留在文件分支），完全不管附带的*结构化*文件里有没有真的相关的：

```python
def question_references_any_attached_file(question, files):
    if any(file.schema_json is None for file in files):
        return True
    return any(question_references_attached_file(question, file) for file in files)
```

具体来说：用户同时附带了 `regional_sales_h1_2026.csv`（结构化，跟问题无关）和 `nimbus_product_onepager.pdf`（非结构化，相关），问"这个产品的定价策略是什么？"PDF 确实相关，所以请求正确地留在了文件分支——但 `_handle_file_data_chat_query` 依然会把*整个* `structured_ids` 子集，包括那份不相关的 CSV，一起交给 `FileDataAgent`。这个函数内部没有任何机制像外层的路由判断那样，再对每份文件单独做一次相关性检查。10.8 在请求层面修好的那个失败模式——LLM 要么在错误的列上瞎凑一个像模像样的答案，要么写出绑定不了的 SQL——依然可能在这里发生，只是现在会跟一个正确的、来自 PDF 的答案共存，而不是让整个请求失败。

## 2. 已经具备的基础

这份设计需要的东西当时都已经写好了，只是没有接到这个具体场景上：

- **`question_references_attached_file(question, file)`**（`src/chatbi/agents/file_query_support.py`）——本来就接受单个文件，返回针对这一份文件的相关性判断结果。10.8 只在 `question_references_any_attached_file()` 内部的聚合 `any(...)` 里调用它；没有任何地方拿它去把一个文件列表过滤成只剩相关的那些。
- **`split_file_ids_by_type(file_ids, files_by_id)`**（10.6）——本来就会在把任一子集交给某个 agent 之前，先把 `structured_ids` 和 `unstructured_ids` 拆开。这份设计只是在这次拆分之后，紧接着再加一道过滤，不是新机制。
- **"没有结构化文件"的兜底路径**（`_handle_file_data_chat_query`，10.5/10.6）——本来就能优雅处理 `structured_ids == ()` 的情况：`federated_output = None; file_output = None`，如果 `unstructured_ids` 那边产出了证据就退回到纯证据回答，否则走既有的 FR-FV10-066 错误路径。把 `structured_ids` 过滤成 `()`，走的就是这条已经测试过的路径，不是新路径。

## 3. 设计：拆分之后立刻过滤 `structured_ids`——但只在真正的混选场景下

```python
files_by_id: dict[str, UserUploadedFile] = {...}  # 不变
structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, files_by_id)

# 把这次问题明显不相关的结构化文件剔除掉——用的是 10.8 在请求层面
# 已经在用的同一个判断函数，只是这里改成按单个文件应用，而不是聚合
# 进 any(...) 里。只在 unstructured_ids 也非空时才生效（第 4 节）。
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

这一点之后的所有逻辑都不用变：`pg_context` 的解析本来就只在 `... and structured_ids` 为真时才会跑，所以如果过滤之后 `structured_ids` 变空了，这一步会自动跳过，不需要新加任何条件判断。`FederatedQueryAgent`/`FileDataAgent` 之后看到的，就只会是这次问题真的看起来相关的那些结构化文件。

对于 10.8 已经在请求层面覆盖的三种情况，这道过滤有两种是空操作：

- **附带的全是结构化文件，全都不相关**——10.8 的外层判断本来就已经让这类请求完全进不了 `_handle_file_data_chat_query`；这道过滤根本不会运行到。
- **附带的全是结构化文件，至少有一份相关**——10.8 的外层判断会放行这类请求；`unstructured_ids` 是空的，`if unstructured_ids:` 这道门禁（第 4 节）会让这道过滤压根不运行——"多份结构化文件、只有部分相关"这种选择组合，本文档最初以为是新增、需要覆盖的行为，等第 4 节发现它跟 10.9 的交互问题之后，结论反过来了：需要明确*排除*，不是纳入。
- **混选，附带了非结构化文件**——第 1 节里的场景：10.8 的外层判断只要有非结构化文件在，就总会放行；这正是这道过滤真正发挥主要作用的场景。

## 4. 测试套件抓住的、跟 10.9 的一次交互问题

这道过滤最初的版本，是无条件运行在 `structured_ids` 上的，没有 `if unstructured_ids:` 这道门禁。写完之后跑了一遍全量测试套件——不只是为这次修复新写的那几条——立刻回归了 [10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.zh-CN.md) 自己的 `test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`：一份单独附带的结构化文件，用了 schema 里没有字面出现过的词汇表述，也没有任何独立的业务数据关键词信号。10.9 存在的全部意义，就是要让这种请求留在文件分支——宁可相信 `FileDataAgent` 自己那个能看到真实 schema 的 LLM，也不要把它路由去一个同样帮不上忙的主编排器。而这道过滤如果无条件运行，跑的正是 10.9 的安全网*已经*在请求层面覆盖过的同一个 `question_references_attached_file()` 判断，在下一层调用里悄悄把 `structured_ids` 重新清空，把那次覆盖撤销了。

修复方式就是第 3 节里的 `if unstructured_ids:` 门禁：只有当确实存在一个可以退回去的替代方案——非结构化证据——的时候，这道过滤才有正当理由运行。一个纯结构化的选择没有这样的替代方案：把它唯一的文件排除掉，只会让请求什么都答不出来，这比让 `FileDataAgent` 做一次有依据的猜测要糟糕得多——而这正是 10.9 已经刻意做出的权衡。这同时也把本文档最初版本第 3 节第二条（多份结构化文件、部分相关、且没有非结构化文件的选择）的结论反过来了：这种情况现在明确*不*被过滤，理由跟单份结构化文件的选择不被过滤是一样的。

## 5. 跟 `FederatedQueryAgent` 的交互

`resolve_federated_pg_context()` 不依赖任何文件的 schema——只看问题文本和实时的业务表 catalog——所以在它跑之前先过滤 `structured_ids`，不会改变它*解析出哪张*业务表，只会影响*还有没有*结构化文件留下来可以跟那张表联表查询（通过现有的 `and structured_ids` 判断）。如果一个混选请求附带了一份跟联表意图相关的结构化文件、一份不相关的，这道过滤会正确地把 `FederatedQueryAgent` 的联表范围收窄到那份相关的文件上，而不是让 LLM 还要费劲去理解一份混进来的、跟这次联表无关的第二份文件的列。

## 6. 验证

新增的 HTTP 层测试（`tests/test_chat_query_with_files.py`）：一个混选场景——一份相关结构化文件、一份不相关结构化文件、一份相关非结构化文件——用一个会记录调用内容的假 LLM client，断言那份不相关文件的 `file_id` 从未出现在 SQL 生成 prompt 里，`table_result` 只反映相关文件的数据；一个混选场景——只有一份不相关的结构化文件和一份相关的非结构化文件——断言 `file_data_sql_generation`/`federated_query_sql_generation` 的 LLM 调用次数是零；一个什么都不相关的混选场景，断言既有的 FR-FV10-066 错误没有变化；以及一个两轮 session，证明某一轮被过滤掉的结构化文件，在之后一轮问一个真正相关的问题时依然完整可用，不受过滤影响。每条新测试里那份不相关的结构化文件，都刻意没有写任何 Parquet 快照——如果过滤退化成依然会碰它，测试会直接因为存储查找失败报错，而不只是断言错了——这跟 10.11 自己提议的、"看 prompt 内容决定输出"的假 LLM client（那份设计的第 10 节）出于同样的理由，都是"让实际机制本身失效时能大声报错"的设计。

10.6 自己既有的混选测试（`test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both`，两份文件都相关）原样重新跑了一遍，没有改动，作为"已相关"情况的回归检查。

在重新构建的 Docker 镜像上，用真实的 OpenAI LLM client 做了实盘复现：一个混选场景（一份跟定价问题无关的销售 CSV，一份跟定价问题相关的文档）返回了 `table_result_source: None`，定价答案正确地完全基于那份文档；反过来的选择（同样这两份文件，问一个针对 CSV 自身数据的问题）返回了 `table_result_source: "file"`，营收数字正确地来自那份文件。

## 7. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-078 | `_handle_file_data_chat_query` 必须在 `split_file_ids_by_type` 拆分之后，把 `structured_ids` 过滤成只剩 `question_references_attached_file()` 判断为相关的那些文件，然后才交给 `resolve_federated_pg_context()` 或 `FileDataAgent`/`FederatedQueryAgent`。 | 已实现 |
| FR-FV10-079 | 这道过滤不得应用到 `unstructured_ids` 上——`FileScopedRetriever` 现有的按单文件相关性处理机制（10.6）不受影响。 | 已实现 |
| FR-FV10-083 | 当 `unstructured_ids` 为空时，这道过滤完全不得运行。一个纯结构化的选择，必须原样交给 10.9 的请求级安全网去判断，不受本设计过滤——这一条是在测试套件对着本设计最初无条件运行的版本，回归了 10.9 自己的测试之后才发现要加的（第 4 节）。 | 已实现 |
| NFR-FV10-027 | 这道过滤不得改变"附带的结构化文件全都已经相关"这种选择组合下的行为（10.6 现有的混选测试必须保持不受影响），也不得改变 `effective_file_ids` 或 session 里为后续轮次存储的文件选择。 | 已实现 |

## 8. 现状：已实现并验证

按本项目通常的 SDD+TDD 顺序实现：先写好 [Spec FV10.10](../../../../spec/final-version/zh-CN/10-followups/10-per-file-relevance-filtering-in-mixed-selections.spec.zh-CN.md)，把它的测试用例先写成针对修复前代码的失败测试、确认每一条都确实因为预期的原因失败，然后再加上第 3 节那四行过滤代码，把测试变绿——中间还有一次修正。第 4 节记录了本项目自己的测试套件在实现过程中抓到的一次真实回归，跟 10.8 那次月份名词元的修复、10.9 那次 `resolve_federated_pg_context()` 的修正是同一种性质的修正，只是抓到的时机比 10.9 晚了一步（10.9 是在任何代码写出来之前就先检查过；这次是代码和测试都已经写好之后，靠跑*既有*测试套件才抓到的）。修复涉及 `src/chatbi/api/http.py` 和 `src/chatbi/agents/__init__.py`（导出 `question_references_attached_file`）；`tests/test_chat_query_with_files.py` 里新增了对应测试；按第 6 节所述，在重新构建的 Docker 镜像上、用真实 LLM provider 做了端到端验证。
