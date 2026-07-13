# 10.8 路由进文件分支之前，加一道问题相关性判断

## 1. 解决的问题

一个用户左侧边栏勾选着 `regional_sales_h1_2026.csv`（列：`region`、`month`、`revenue`、`orders`）——是前一轮问题遗留下来的勾选状态——然后点了一个 Quick Question 快捷按钮，问的是"Compare total ticket count by product in H1 2026."。返回结果是 `AGENT_PARTIAL_FAILURE: "The file query could not be completed."`。这个问题跟附带的这份文件完全没关系：文件里压根没有任何工单或产品数据。但这套系统里确实存在一张真实的 `business.support_ticket_summary` 表，本来是能回答这个问题的——只是这次请求根本没有机会走到能查那张表的代码路径。

在运行中的容器上，针对完全相同的问题和文件 schema，直接重放了 `FileDataAgent` 的 SQL 生成 prompt（5 次，`temperature=0.0`，每次结果完全一致），复现如下：

```sql
SELECT region, SUM(orders) AS total_orders
FROM file_ufile_7b27e853fb394ba4818885d6a7b3a3ee
WHERE month IN ('2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06')
GROUP BY region;
```

面对一份跟"ticket"或"product"毫不相干的 schema，模型就近拿了最接近的数值列（`orders`）凑数，实际回答的是另一个完全不同的问题——SQL 语法上合法，语义上却是错的。在另一种历史对话组合下（比如前面刚查过 `regional_sales.csv`——一份确实有 `product` 列的姊妹文件），同样的机制会生成引用了 `product` 列的 SQL，但这份文件根本没有这一列，DuckDB 的 binder 会直接拒绝——`InvalidGeneratedSqlError`——表现出来就是报告里那个 `AGENT_PARTIAL_FAILURE`。这两种结果其实是同一个缺口的两种表现：不管模型写出什么 SQL，被强行拉去回答这个问题的这份文件，压根就答不了。

## 2. 已经具备的基础

`chat_query_v2()`（`http.py`）此前做的是一个纯二选一的路由判断，只看一个事实——`effective_file_ids` 是否非空——完全不考虑这个问题到底在问什么：

```python
if effective_file_ids:
    api_envelope = _handle_file_data_chat_query(...)   # 只走文件分支
else:
    api_envelope = chatbi_application.handle_chat_query(...)   # 走主编排器
```

[10.4](04-multi-turn-conversation-memory.zh-CN.md) 特意把文件附件做成了按会话延续的——就是为了让用户不用每一轮追问都重新选一次文件——`resolve_effective_file_ids()` 会在请求没带 `file_ids` 时，把上一次的选择继续带下去。而恰恰是这个设计选择，才让"过期、早就不相关的选择"变得可能：三轮之前为了一个跟文件相关的问题附带的文件，五轮之后问一个完全无关的问题时，不管有没有重新显式选择，依然还是 `effective_file_ids`。`FileDataAgent` 和 `FederatedQueryAgent` 都没有"这个问题跟你的数据无关"这种输出——[10.6](06-hybrid-file-answering-for-mixed-selections.zh-CN.md) 已经给混选里的*非结构化*那一半做好了这个能力（`FileScopedRetriever` 对不相关的内容就是直接返回空证据，调用方本来就能优雅处理这种情况），但*结构化*那一半一直没有对应的机制：LLM 永远被要求生成一条 `SELECT`，它也永远会生成一条——不管眼前这个 schema 跟问题到底有没有关系。

## 3. 设计：用词元重合度做相关性判断，不调用 LLM

`question_references_attached_file()`（`src/chatbi/agents/file_query_support.py`）在不调用任何模型的情况下，判断一个问题是否有可能跟某份文件相关：

```python
def question_references_attached_file(question: str, file: UserUploadedFile) -> bool:
    if _tokenize(question) & _FILE_REFERENCE_HINTS:
        return True

    question_tokens = _content_tokens(question)
    if not question_tokens:
        return True

    file_tokens = _content_tokens(file.original_name)
    if file.schema_json is not None:
        for column in file.schema_json["columns"]:
            file_tokens |= _content_tokens(str(column["name"]))

    return bool(question_tokens & file_tokens)
```

三处刻意做的排除，让它不至于沦为一个天真的词袋匹配：

- **停用词**（`_STOPWORDS`）——"what"、"is"、"my"、"please"、"just" 等——在两边都不算相关性信号；不排除的话，几乎任意两句英文都会"碰巧重合"。
- **泛化的日期/季度词元**（`_GENERIC_DATE_TOKEN`，匹配纯数字或 `h1`/`h2`/`q1`–`q4`）——这次报告的 bug 里，那份文件本身就叫 `regional_sales_h1_2026.csv`，出问题的那个问题结尾正好是"...in H1 2026."。如果不排除这些词元，光靠文件名的匹配，就会让这道判断对着这个本该判"不相关"的问题说"相关"。
- **具体的月份名**（`_MONTH_NAME_TOKEN`，"january"……"december" 及其缩写）——这是在早期版本的判断逻辑弄坏了一个*既有*测试之后才发现要加的（见第 5 节）："And just June?"，作为一次针对某份 `month` 列存的是 `"2026-06"` 的文件问出的合法追问，跟这份文件没有任何字面词元重合。列名 `month` 本身刻意*没有*被列进这个排除表——那是一次真实、具体的 schema 匹配；只有用户可能随口打出来的具体月份*取值*才足够泛化，该被排除。

第四条规则是"安全网"，正是有了它，前三条才能放心做得这么严格：**去掉停用词、泛化日期词元、月份名之后，如果问题里已经没有任何有实质内容的词元，这道判断默认判"相关"。**一个纯代词式的追问，比如"What about this one?"，不管针对的是哪份文件，去掉停用词之后都不剩任何内容词元——这个函数没法对它做判断，也就不硬判。它把这种情况交还给本来就是为解决这个问题而存在的机制：对话历史注入（Spec FV10.4）。

`question_references_any_attached_file()` 是路由层面的封装：只要附带的文件里*任意一份*是非结构化的（它自己的相关性判断是 `FileScopedRetriever` 的职责，按 10.6 的分工，不归这道判断管），或者*任意一份*结构化文件单独通过了 `question_references_attached_file()`，就判定为相关。

## 4. 设计：把这道判断接进路由决策

`chat_query_v2()` 原本的二选一判断，现在多了第三个输入：

```python
effective_files = tuple(
    file for file in (active_file_repository.get(fid) for fid in effective_file_ids) if file is not None
) if effective_file_ids else ()
route_to_file_branch = bool(effective_file_ids) and question_references_any_attached_file(
    str(body["question"]), effective_files
)
if route_to_file_branch:
    ...  # 文件分支，未变
else:
    ...  # 主编排器分支，未变
```

当这道判断认为"不相关"时，这次请求会被当成完全没带 `file_ids` 一样处理——`effective_file_ids` 本身、以及 session 里存的那份选择，都不受影响，所以同一 session 里*之后*真正跟文件相关的问题，依然能看到这份文件是附带着的。改变的只是这一轮的路由决策。

## 5. 验证，包括一次自己抓住的回归

针对这个判断函数的单元测试（`tests/test_file_query_support.py`）覆盖了：列名匹配、这次报告的 bug 里那个完全无关的原问题、`h1`/`2026` 跟文件名的巧合、`"file"`/`"uploaded"` 这类提示词、一个内容词元为空的代词式问题——以及最关键的一个：一个孤零零的月份名。

最后这一条测试的由来是：这道判断的早期版本没有排除月份名，跑全量测试时立刻抓到了问题——`tests/test_multi_turn_conversation.py::test_third_turn_inherits_the_second_turns_explicit_file_not_the_first` 从通过变成了失败。它的第二轮问题"What about this one?"依然能通过（没有内容词元，默认判相关）——但一次相关的手动检查，用"What about just June?"去问一份把 `month` 存成 `"2026-06"` 的文件，就把这个缺口暴露出来了：这道判断没法区分"问题提到的东西大概率就是这份文件自己的"和"问题提到的是同一类东西、但写法跟这份文件存的不兼容"。把 `_MONTH_NAME_TOKEN` 加进排除表——同时把 `just` 也加进停用词表，因为只排除"june"的话，还会剩下一个孤立、不重合的 `"just"` 词元——修好了这个问题，同时没有削弱这道判断真正要拦截的那种情况。

一个 HTTP 层面的回归测试（`tests/test_chat_query_with_files.py::test_chat_query_with_a_structured_file_irrelevant_to_the_question_routes_to_main_orchestrator`）直接复现了报告里的 bug：附带一份有 `month`/`revenue` 列的结构化文件，问一个不相关的问题，断言 `table_result_source is None`——证明是主编排器在回答，不是文件分支。

在重新构建的 Docker 镜像上，用真实的 `regional_sales_h1_2026.csv` 文件和真实的 OpenAI LLM client 做了实盘复现：

- 报告里那个问题现在返回 `table_result_source: None`，答案是从 `business.support_ticket_summary` 真实计算出来的，不再是 `AGENT_PARTIAL_FAILURE`。
- 同一 session 里的追问——先问"What is my revenue by region?"，再问"What about just June?"——两次都返回 `table_result_source: "file"`，说明这道判断没有误伤这次追问。

1357 个不需要连真实 Postgres、也不需要构建好的前端包的测试全部通过；本次改动之前就存在、跟本次改动无关的失败（需要 Postgres 凭据的测试、断言前端包内容的测试、一个 markdown 链接解析测试）在改动前后数量和具体项都没有变化。

## 6. 已知限制——本次没有解决

- **这是一个启发式判断，不是真正的理解。**它是"词元重合度 + 几条有依据的排除规则"，不是语义匹配。一个确实跟附带文件相关、但用词跟文件的列名/文件名完全不沾边的问题（比如用了文件列名里没有的业务同义词），依然可能被误判为"不相关"、转去主编排器。跟 [10.7](07-cross-turn-value-format-contamination-in-file-sql-generation.zh-CN.md) 的失败模式不一样，这里的假阴性产出的是一个*不同方向的错误*答案（或者主编排器干脆诚实地说"不知道"），而不是文件分支那种*信心满满的错误*答案——这在"错误的种类"上是真正的改善，但不代表路由永远正确。
- **这道判断是按整个请求做全有全无的判断，不是按单个文件过滤的。**对于结构化+非结构化的混选，只要附带的文件里*有任何一份*是非结构化的或相关的，`question_references_any_attached_file()` 就会让整个请求留在文件分支——它不会像 [10.6](06-hybrid-file-answering-for-mixed-selections.zh-CN.md) 已经按文件*类型*做的那样，把一份跟问题无关的结构化文件从这次请求的 `structured_ids` 里单独过滤掉。一份跟问题无关的结构化文件，只要跟一份相关的非结构化文件一起附带，依然会被送进 `FileDataAgent`，依然可能产出本文档原本要修的那种"答错列"或"绑定报错"的行为——只是范围缩小到了混选这一种具体场景，不是这次报告的场景。
- **排查过程中一并发现的另一个、依然没解决的问题，不是靠这道判断或 10.7 就能修的：** 即便路由正确地把问题留在了文件分支，`FileDataAgent` 的 SQL 生成始终只能看到某一列的*名字和类型*（`month VARCHAR`），从来看不到这一列实际存的*取值*长什么样。直接打在*当前*这一轮问题里的自然语言日期表述——不是从早前轮次带过来的，所以 10.7 的修复对它不生效——依然可能被翻译成一个跟文件实际格式对不上的字面量（比如对着存 `'2026-06'` 的列写出 `WHERE month = 'June'`），产出跟 10.7 诊断出的那种"合法但为空"一模一样的失败，只是原因不同。要彻底解决这个问题，需要给到 LLM 的 schema 上下文里带上每一列实际取值的少量样本，而不只是它声明的类型——这需要改 `FileDataAgent.build_schema_context()` 和 `FederatedQueryAgent` 里对应的逻辑，不在本次范围内。

## 7. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-074 | `chat_query_v2()` 不得仅仅因为 `effective_file_ids` 非空就把请求路由进文件分支（`_handle_file_data_chat_query`）；还必须通过 `question_references_any_attached_file()` 确认至少有一份附带文件跟当前问题大概率相关。 | 已实现 |
| FR-FV10-075 | 一份附带的非结构化文件，必须始终被当作"请求应该留在文件分支"的充分理由——它自己内容的相关性判断是 `FileScopedRetriever` 的职责（按 10.6 的分工），不归这道判断管。 | 已实现 |
| FR-FV10-076 | 去掉停用词、泛化日期词元、月份名之后，如果问题里没有任何有实质内容的词元（比如一个纯代词式的追问），必须默认判为相关，交还给对话历史解析机制（Spec FV10.4）处理，而不是由这道判断硬判。 | 已实现 |
| NFR-FV10-025 | 当这道判断把某一轮请求路由离开文件分支时，不得改变 `effective_file_ids` 或 session 里存的文件选择——只影响这一轮的路由决策；同一 session 里之后一个确实相关的问题，依然要能看到这份文件是附带着的。 | 已验证——`resolve_effective_file_ids()` 的调用、以及 session 存储的更新，都发生在这道判断执行之前；这道判断只影响后面那一个 `if`。 |

## 8. 现状：已修复并验证

这次缺陷是通过对一个用户反馈的失败案例做直接的生产容器复现发现的，修复方式跟 10.5、10.7 一样：没有预先设计，缺陷先于设计存在。这道判断函数和它的排除表，在实现过程中还被本项目自己的测试套件抓到一次回归后又修正过一次（第 5 节）——这正是本项目 SDD+TDD 惯例存在的意义：在合并之前而不是之后暴露这类问题。修复涉及 `src/chatbi/agents/file_query_support.py`，通过 `src/chatbi/agents/__init__.py` 重新导出，并接入了 `src/chatbi/api/http.py`；`tests/test_file_query_support.py` 和 `tests/test_chat_query_with_files.py` 里新增了对应测试；按第 5 节所述，在重新构建的 Docker 镜像上、用真实 LLM provider 做了端到端验证。第 6 节列出的那些限制，是同一次排查过程中一并发现的，本次修复有意没有把它们纳入范围，留给未来的后续文档处理。
