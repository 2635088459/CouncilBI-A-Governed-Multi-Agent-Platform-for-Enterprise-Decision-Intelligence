# 10.7 文件/联邦查询 SQL 生成中的跨轮次取值格式污染

## 1. 解决的问题

一个用户在一个已经问了好几轮无关问题（工单数量、营收趋势等）的会话里，上传了一份结构化 CSV（`regional_sales_h1_2026.csv`，其中 `month` 列的格式是 `"2026-01"`..`"2026-06"`），连同一份非结构化笔记一起选中，问了一个这份 CSV 本该能直接回答的问题。返回结果的列名是对的，但一行数据都没有——LLM 如实地基于给到它的东西写道"regional sales file did not return any data"，然后退回到只用那份非结构化笔记来回答。同样的问题，如果作为一个全新会话的第一条消息、附带同样的文件去问，回答是正确的。

"只有第一轮才正常"这一点排除了文件处理链路本身的问题——上传、解析、Parquet 快照、schema 推断、DuckDB 视图注册，第一轮成功已经证明这些环节都在正常工作。定位缺陷的方法是：在运行中的容器里，把 `FileDataAgent._generate_sql()` 实际构造的 prompt 原样重放给 OpenAI provider——一次不带任何历史轮次，一次带上用户那次会话里实际存在的那一轮无关历史。不带历史时，模型写的是：

```sql
SELECT region, SUM(revenue) AS total_revenue, SUM(orders) AS total_orders
FROM file_ufile_adeada000b3c47dba073a99eebd9429a
GROUP BY region;
```

带上那一轮历史——一个"月度营收趋势"问题，回答内容来自一张无关的业务表，回答里把月份写成了 `"January"`、`"February"`……——之后，模型在 `temperature=0.0` 下连续三次调用，确定性地写出：

```sql
SELECT region, SUM(revenue) AS total_revenue, SUM(orders) AS total_orders
FROM file_ufile_adeada000b3c47dba073a99eebd9429a
WHERE month IN ('January', 'February', 'March', 'April', 'May', 'June')
GROUP BY region;
```

这两条 SQL 都是针对正确的表、带着正确列名的合法 DuckDB SQL——都不会触发 `find_blocked_statement()`，也不会抛出 `duckdb.Error`，所以整条链路里没有任何一处把它们当成失败处理。第二条只是恰好匹配不到任何一行，因为这份 CSV 的 `month` 列存的是 `'2026-01'`..`'2026-06'`，不是英文月份名。模型在没人要求的情况下，把早前一轮里、来自一张无关表的取值格式，带进了针对一张不用这种格式的表的 `WHERE` 子句里。

本文档记录的是针对这一具体污染问题的修复。它不覆盖——见第 6 节——这次排查过程中同时发现的另一个相邻缺口：一次"合法但为空"的文件查询结果，目前在 HTTP 层跟"这份文件确实没有匹配数据"是无法区分的。

## 2. 已经具备的基础

[10.4](04-multi-turn-conversation-memory.zh-CN.md) 把"把历史轮次注入 prompt"定为这套代码库里唯一的追问消解机制：文件分支里完全没有单独的查询改写步骤。`chat_query_v2()`（`http.py`）会从 `shared_query_history`——跟主编排器路径共用的同一个存储——里读出这个 session 最近 `conversation_context_turns` 条记录，原样当作普通聊天消息，拼在当前问题前面：

```python
history_turns = shared_query_history.list_by_session(
    session_id, limit=active_runtime_config.conversation_context_turns
)
api_envelope = _handle_file_data_chat_query(
    ...,
    conversation_context=conversation_messages(history_turns),
)
```

`FileDataAgent._generate_sql()` 和 `FederatedQueryAgent._generate_sql()`（`src/chatbi/agents/file_data_agent.py`、`src/chatbi/agents/federated_query_agent.py`）随后都用同样的方式构造 LLM 请求：

```python
messages=(
    {"role": "system", "content": system_prompt},
    *request.conversation_context,   # 历史轮次，原样拼接
    {"role": "user", "content": request.question},
),
```

`shared_query_history` 是真正"共享"的：不管是哪条分支产出的回答，都会存进同一个 session 的历史里——一条针对 `revenue_by_month` 的纯 SQL 编排器轮次、一条纯 RAG 轮次、一条文件分支轮次，在 `QueryHistoryRecord` 里是完全同一种记录，里面没有任何字段标注这条记录是哪个 agent 产出的、查询的是哪张表。这是 10.4 当初刻意做的简化选择——只用一个共享历史存储，不做分支级别的记账——而正是这个选择，让一条无关业务表轮次里的月份命名格式，能够渗进一次文件查询的 `WHERE` 子句里：整条链路里没有任何东西能区分"这一轮和当前查询是同一份数据"跟"这一轮只是恰好比较新"。

在这次修复之前，`conversation_context_turns`（`RuntimeConfig`，默认 `5`）是唯一控制"多少历史会进到这个 prompt 里"的开关，而且是所有读它的分支共用的。

## 3. 设计：明确指示模型不要照抄历史轮次里的取值格式

两个 agent 构造的 system prompt，此前对"该怎么处理 `conversation_context`"完全没有交代，隐含地指望模型自己判断得当。现在明确写清楚了：

```python
system_prompt = (
    "You are a DuckDB SQL generator. Reply with exactly one DuckDB "
    "SELECT statement that answers the user's question and nothing "
    "else: no explanation, no markdown code fences, no prose.\n\n"
    f"Available tables:\n{schema_context}\n\n"
    "Prior conversation turns, if present, may be about a different "
    "table or data source with different value formats (e.g. month "
    "names vs. 'YYYY-MM' strings). Use them only to resolve "
    "pronouns or follow-up references in the current question (e.g. "
    "'and July?'). Never copy a literal value or format from an "
    "earlier turn into this query — every literal must match the "
    "actual values in the tables listed above."
)
```

这是 prompt 层面的约束，不是代码层面的保证——这里没有任何机制在结构上阻止模型不遵守这条指示。它之所以要搭配第 4 节一起做，是因为单靠 prompt 指示只是一种概率性的缓解手段，而这个项目一贯的做法（见 [10.5](05-rag-only-routing-and-promotion-durability.zh-CN.md) 第 6 节"大声报错，不要悄悄地少给东西"）是：只要还剩下纯行为层面的修复这一个手段，也要在结构上尽量把影响范围缩小。

`FileDataAgent._generate_sql()` 和 `FederatedQueryAgent._generate_sql()` 收到了完全一样的改动——它们用同一套 `build_schema_context()` 辅助函数、以同样的方式构造 system prompt，也因为同样的原因带着同样的缺陷。

## 4. 设计：给文件分支一个更窄、专属的历史窗口

`conversation_context_turns` 继续按 10.4 原本的设计，控制主编排器的追问消解——那条路径上前后几轮问题更有可能围绕同一批业务表展开，窗口开大一些风险相对更低。文件分支则拿到了一个独立的、更小的默认值：

```python
# RuntimeConfig
conversation_context_turns: int = 5
file_conversation_context_turns: int = 2
```

```python
# load_runtime_config()
file_conversation_context_turns=_positive_int(
    runtime_env.get("CHATBI_FILE_CONVERSATION_CONTEXT_TURNS"), 2
),
```

```python
# http.py, chat_query_v2() —— 仅文件分支
history_turns = shared_query_history.list_by_session(
    session_id, limit=active_runtime_config.file_conversation_context_turns
)
```

理由是：用户上传的文件，按定义就不是组织治理下的业务表之一，所以同一 session 里的前一轮，反而*更*有可能——而不是更不可能——来自跟刚附加的这份文件形状不同的数据源。在没有办法标注"哪些历史轮次真的跟当前 `file_ids` 相关"（见第 6 节）之前，唯一能用的结构性手段就是"暴露时长"：读进 prompt 的历史轮次越少，SQL 生成时 prompt 里恰好躺着一个无关取值格式的机会就越少。这并不能消除这个失败模式本身——如果那条无关轮次恰好就问在文件问题的前一轮、落在（现在变窄的）窗口之内，它依然会进到 prompt 里，届时只靠第 3 节的指示来兜底——它降低的是这个窗口里出现无关内容的频率。

## 5. 验证

在正在运行的 Docker 环境上、用真实的 OpenAI LLM client（不是走确定性的 mock provider——这个缺陷是真实模型跨轮次泛化方式特有的，用 `MockLLMProvider` 复现不出来，因为它是按 `task_type` 做模式匹配，根本不会看 conversation history）复现：

- **修复前**，在一个带一轮无关历史的 session 里：`table_result` 返回 `{"columns": ["region","total_revenue","total_orders"], "rows": []}`——连续 3 次确定性复现。
- **修复后**，重新构建 backend/worker 镜像、重放完全相同的两轮 session：`table_result` 正确返回了两行数据，营收和订单合计都对，最终合成的回答也直接引用了这些数字，不再退回到只用非结构化证据。
- 更长的链条（四轮无关历史，超出了新的两轮窗口）之后再问同样的文件问题，回答依然正确——说明变窄的窗口本身没有饿死一次真正合法的同 session 追问（"总结一下这份文件"这个问题本来就不需要靠历史轮次去消解任何代词）。

改动之后跑了 `tests/test_runtime_config.py`、`tests/test_file_data_agent.py`、`tests/test_federated_query_agent.py`、`tests/test_chat_query_federated.py`、`tests/test_v2_chat_query_http.py`，全部通过，只有 `test_v2_chat_query_http.py` 里两个跟本次改动无关、需要连真实 Postgres（当前环境没有对应凭据）的既有失败用例。

## 6. 已知限制——本次没有解决

- **没有做相关性标注。**`QueryHistoryRecord` 目前仍然不记录某一轮到底涉及哪些 `file_ids` 或哪张表。第 4 节的修复是个粗手段——缩短时间窗口，而不是做相关性过滤——因为构建真正的过滤器所需要的数据目前根本不存在。一轮三个轮次之前、确实跟当前文件相关的历史，现在会被排除在外，明明它本来是可以合法使用的上下文；而一轮跟当前完全无关、但恰好是上一轮问的历史，依然会被带进去。要真正做出一个过滤器（给 `QueryHistoryRecord` 标注它用到的 `file_ids`/表，让文件分支只注入跟当前请求至少共享一个 `file_id` 的历史轮次），改动规模比这次修复大得多，不在本次范围内。
- **一次失败或为空的结构化查询，在下游依然跟"这份文件本来就没有匹配数据"无法区分。**这次的缺陷恰好表现为"合法但为空"的 SQL，而 `_handle_file_data_chat_query` 里从来没有把这种情况当成错误处理过——`http.py` 里 `if table_result is None and not uploaded_file_evidence:` 这条判断，只有在完全没有非结构化证据可以顶上的时候，才会把 `structured_error_code`（比如 `INVALID_GENERATED_SQL`）暴露出来。只要请求里同时附带了一份确实能检索出证据的非结构化文件——本次报告的案例正是这样——一次失败或为空的结构化查询就会被悄悄吸收进一个"只靠证据"的回答里，响应里没有任何东西能区分"文件查询确实什么都没查到"和"文件查询坏了、但没人被告知"。这次排查发现并修复的是导致某一次"为空结果"的*具体*原因，并没有改变"任何为空或失败的结构化查询结果该如何呈现给调用方"这件事。这是一个更大、更独立的设计问题——多来源回答里某一条分支失败、但另一条分支依然产出了东西时，该向谁、报告什么——留给未来的后续文档处理。
- **第 3 节里的指示没有强制力。**换一个足够不同、或者对字面量更"较真"的模型，或者这个请求里其他地方未来的 prompt/模型变动，仍然有可能在（现在变小的）历史窗口内复现最初的失败模式。第 3 节和第 4 节合在一起降低的是概率；两者都不是硬性保证。

## 7. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-071 | `FileDataAgent._generate_sql()` 和 `FederatedQueryAgent._generate_sql()` 构造的 system prompt，必须明确告诉模型：历史对话轮次可能来自不同的表/数据源、取值格式可能不同；历史轮次只能用来消解代词或追问引用；生成的 SQL 里每一个字面量都必须来自同一个 prompt 里列出的表 schema，不能照抄早前轮次里的内容。 | 已实现 |
| FR-FV10-072 | 文件分支（`chat_query_v2()` 调用 `_handle_file_data_chat_query` 的地方）读取会话历史时，必须使用一个专属的 `file_conversation_context_turns` 限额，跟主编排器的 `conversation_context_turns` 相互独立、可分别配置，默认值为 `2`。 | 已实现 |
| FR-FV10-073 | `file_conversation_context_turns` 必须能通过环境变量 `CHATBI_FILE_CONVERSATION_CONTEXT_TURNS` 配置，校验和"无效值回退默认值"的行为要跟 `CHATBI_CONVERSATION_CONTEXT_TURNS` 保持一致（非空、正整数）。 | 已实现 |
| NFR-FV10-024 | 本次改动不得改变"session 里没有任何历史轮次"（`conversation_context` 为空）时文件查询的 SQL 生成行为，也不得改变主编排器路径对 `conversation_context_turns` 的使用方式。 | 已验证——第 5 节的复现过程确认了首轮和主编排器路径的行为没有变化。 |

## 8. 现状：已修复并验证

这次缺陷是通过直接在生产容器上复现定位出来的，不是提前设计出来的——跟 10.5 那两个缺陷的发现方式一样。修复涉及 `src/chatbi/agents/file_data_agent.py`、`src/chatbi/agents/federated_query_agent.py`、`src/chatbi/core/runtime_config.py`、`src/chatbi/api/http.py`；`tests/test_runtime_config.py` 里新增了对应测试；按第 5 节所述，在重新构建的 Docker 镜像上、用真实 LLM provider 做了端到端验证。第 6 节列出的那些限制,是同一次排查过程中一并发现的,这次修复有意没有把它们纳入范围,留给未来的后续文档处理。
