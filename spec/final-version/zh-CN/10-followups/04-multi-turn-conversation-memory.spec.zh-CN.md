# Spec FV10.4：多轮对话记忆

来源设计文档：
- [10.4 多轮对话记忆设计](../../../system_design/final-version/zh-CN/10-followups/04-multi-turn-conversation-memory.zh-CN.md)
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；`session_id` 已经是 `ChatQueryRequestV2` 的一部分；本 Spec 修正 `_handle_file_data_chat_query` 里"是否带 file_ids"这个路由分支）

---

## 1. 目的

定义按会话隔离的对话上下文：SQL 生成、RAG 检索、答案综合都要能考虑当前会话最近几轮的内容，这样一个追问（比如"那七月份呢？"）不需要用户重复上下文就能被正确回答。初次设计评审时标注为未决的两个行为，现在都已经确认：文件附件在一个会话内跨轮次延续（方案 A），追问完全依靠消息历史解析，不设单独的显式改写步骤（方案 B）。本 Spec 把两者都定义成可测试的需求。

## 2. 范围

**纳入范围：**
- 检索一个会话最近 N 轮的查询历史。
- 把这些历史轮次作为对话上下文注入 SQL 生成、RAG 检索、答案综合。
- 可配置的上下文窗口大小。
- 前端：把一个会话渲染成连续的对话线程，并提供明确的"开始新会话"操作。
- 按会话隔离的 `file_ids` 继承：一次没有 `file_ids` 的请求，沿用该会话最近一次显式传入的非空 `file_ids`。
- 追问（指代词、省略句）的引用解析完全依靠 FR-FV10-052 提供的消息历史——不设单独的改写调用。

**不纳入范围：**
- `session_id` 生成方式或格式的任何改动（不变）。
- 超出上下文窗口的更早轮次的摘要压缩（未定义；如果实践中发现窗口太短，那是后续再决定的事，不属于本 Spec）。
- 一个明确的"把这个文件从会话里摘除"的操作——想不再用继承下来的文件，唯一的办法是显式传一个不同的 `file_ids`，或者开一个新会话。

## 3. 参与方

沿用父 Spec FV-10 第 3 节定义的参与方。不引入新参与方。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-051 | 查询历史存储必须支持按给定 `session_id` 检索最近 N 条 `QueryHistoryRecord`，按从旧到新排序，N 由调用方指定。 |
| FR-FV10-052 | SQL 生成（`sql_agent`、`FileDataAgent._generate_sql`、`FederatedQueryAgent._generate_sql`）、RAG 检索、`GroundedAnswerSynthesizer`，每次调用都必须收到当前会话最近几轮作为额外的对话上下文。 |
| FR-FV10-053 | 纳入的轮次数量（上下文窗口）必须是可配置值，不能写死，默认为 5。 |
| FR-FV10-054 | 前端必须把当前 `session_id` 内的所有轮次渲染成一条连续、追加式的对话线程，并且必须提供一个明确的操作，能开启一个新的 `session_id` 和一条视觉上清空的线程，同时不删除上一个会话的历史。 |
| FR-FV10-055 | 一次 `file_ids` 为空或未传的对话查询请求，必须继承该会话最近一次显式传入的非空 `file_ids`（如果存在的话），并且必须按跟客户端显式传了一样的方式，走文件查询这条路由分支。一次显式传入非空 `file_ids` 的请求，必须使用该值，并且必须让它成为该会话之后轮次的新继承值。如果一个会话此前从未显式传过 `file_ids`，那么一次 `file_ids` 为空的请求必须当作没有文件处理（没有可以继承的东西）。 |
| FR-FV10-056 | SQL 生成、RAG 检索、答案综合，解析追问引用（指代词、省略句）时，必须只依靠 FR-FV10-052 注入的对话历史消息。系统在生成 SQL 或检索 RAG 证据之前，不得进行任何单独的显式问题改写调用。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-018 | 加入对话上下文，不得增加单轮查询（会话里的第一个问题）的 P95 延迟，因为这种情况下根本没有历史需要获取或注入。 |
| NFR-FV10-019 | 上下文窗口（FR-FV10-053）必须作为硬性上限强制生效——一个历史轮次超过 N 的会话，必须只注入最近 N 轮，绝不能注入全部历史。 |
| NFR-FV10-020 | 一个会话继承的 `file_ids` 状态（FR-FV10-055）不得被任何其他 `session_id` 看到或继承，即使是同一个登录用户的其他会话也不行。 |

## 6. 数据契约

### 6.1 `InMemoryQueryHistory`（扩展后）

```python
def list_by_session(self, session_id: str, *, limit: int = 5) -> tuple[QueryHistoryRecord, ...]:
    """一个会话最近 limit 轮，按从旧到新排列。"""
```

### 6.2 对话上下文的形态

历史轮次以普通的聊天消息形式注入，不是自定义的摘要格式：

```python
def conversation_messages(records: tuple[QueryHistoryRecord, ...]) -> tuple[dict[str, str], ...]:
    """对每条记录依次产出交替的 {"role": "user", "content": question}、
    {"role": "assistant", "content": answer_text}，按从旧到新排列，
    可以直接拼在某次 LLM 调用的消息序列最前面。"""
```

### 6.3 运行时配置

新增环境变量 `CHATBI_CONVERSATION_CONTEXT_TURNS`（默认 `5`），解析方式跟 `chatbi/core/runtime_config.py` 里其他整数类运行时配置一致，支撑 FR-FV10-053。

### 6.4 会话文件继承（FR-FV10-055）

新增一个小型的独立存储——跟 `InMemoryQueryHistory` 那个有限的上下文窗口无关，因为一个会话围绕同一个文件聊的轮次，完全可能比窗口保留的轮数多：

```python
class SessionFileContext(Protocol):
    def get_active_file_ids(self, session_id: str) -> tuple[str, ...]:
        """该会话最近一次显式传入的非空 file_ids；不存在则返回 ()。"""
        ...

    def set_active_file_ids(self, session_id: str, file_ids: tuple[str, ...]) -> None:
        """把 file_ids 记录为该会话新的继承值。只在 file_ids 非空时被调用。"""
        ...
```

`chat_query_v2` 在原有的 `_handle_file_data_chat_query` vs. 主编排器路由判断之前调用的解析辅助函数：

```python
def resolve_effective_file_ids(
    explicit_file_ids: tuple[str, ...],
    session_id: str,
    session_file_context: SessionFileContext,
) -> tuple[str, ...]:
    """FR-FV10-055：显式传入的 file_ids 永远优先，并成为新的继承值；
    否则沿用该会话当前的继承值，不存在则返回 ()。"""
    if explicit_file_ids:
        session_file_context.set_active_file_ids(session_id, explicit_file_ids)
        return explicit_file_ids
    return session_file_context.get_active_file_ids(session_id)
```

`chat_query_v2` 必须调用 `resolve_effective_file_ids()`，并且不管是路由判断（`if file_ids:`）还是下游所有用到 `file_ids` 的地方（`_validate_chat_query_file_ids`、`_handle_file_data_chat_query`、审计记录），都必须使用这个函数的返回值，而不是请求体里原始的 `file_ids` 字段。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-044 | 同一会话里的第二个问题，指代第一个问题的主题（比如"那再往前一个月呢？"），能在用户不重述主题的情况下，利用第一轮的上下文被正确回答。 |
| AC-FV10-045 | 同一用户在**不同** `session_id` 下提出的问题，不会拿到第一个会话的任何上下文——回答方式跟这是有史以来问的第一个问题一样。 |
| AC-FV10-046 | 一个历史轮次超过配置的上下文窗口的会话，下一次 LLM 调用里只包含最近一个窗口大小的历史，通过检查实际构造出的消息列表来验证。 |
| AC-FV10-047 | 前端把当前会话的所有轮次显示成一条连续的对话线程；点击"开新对话"会开启一条视觉上清空的线程，之前的会话仍然可以通过现有的聊天历史接口查到。 |
| AC-FV10-048 | 第一轮附加了 `file_ids=[X]`；同一会话第二轮 `file_ids` 为空，能用文件 X 正确回答（走文件查询这条路由分支），客户端不用重新传 `file_ids`。 |
| AC-FV10-049 | 跟 AC-FV10-048 同一会话的第三轮显式传入 `file_ids=[Y]`，会用 Y 回答，而不是继承的 X；之后 `file_ids` 为空的第四轮，继承的是 Y，不是 X。 |
| AC-FV10-050 | 一个全新会话里、有史以来的第一个问题，`file_ids` 为空，走的是主编排器（不是文件查询分支）——因为没有可以继承的东西。 |
| AC-FV10-051 | 一个完全靠消息历史上下文解析的追问，能得到正确答案，而且这一轮实际发起的 LLM 调用次数，跟一个结构等价的"第一轮问题"发起的调用次数一致（也就是说没有额外插入一次改写调用）。 |

## 8. 测试计划

### 8.1 单元测试 —— 会话历史检索

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-137 | unit | 某会话存在 8 条记录时，`list_by_session(session_id, limit=5)` 返回该会话最近的 5 条，按从旧到新排列。 |
| TC-FV10-138 | unit | 对一个不存在任何记录的 `session_id`，`list_by_session()` 返回空元组。 |
| TC-FV10-139 | unit | `list_by_session()` 绝不会返回属于不同 `session_id` 的记录。 |

### 8.2 单元测试 —— 上下文注入

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-140 | unit | 对一段 3 条记录的历史，`conversation_messages()` 按时间顺序产出交替的 user/assistant 消息。 |
| TC-FV10-141 | unit | `sql_agent`/`FileDataAgent`/`FederatedQueryAgent` 针对第二轮问题发起的 LLM 调用，包含第一轮的问答作为前置消息。 |
| TC-FV10-142 | unit | 针对全新会话里的**第一个**问题发起的 LLM 调用，不包含任何对话历史消息（空历史，不是报错）。 |

### 8.3 单元测试 —— 会话文件继承

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-146 | unit | `resolve_effective_file_ids(explicit=("ufile_x",), ...)` 返回 `("ufile_x",)`，并调用 `set_active_file_ids(session_id, ("ufile_x",))`。 |
| TC-FV10-147 | unit | 某会话的 `get_active_file_ids()` 返回 `("ufile_x",)` 时，`resolve_effective_file_ids(explicit=(), ...)` 返回 `("ufile_x",)`。 |
| TC-FV10-148 | unit | 某会话的 `get_active_file_ids()` 返回 `()` 时，`resolve_effective_file_ids(explicit=(), ...)` 返回 `()`。 |
| TC-FV10-149 | unit | 调用 `set_active_file_ids("ses_A", ("ufile_x",))` 不会改变另一个会话 `get_active_file_ids("ses_B")` 的结果（对应 NFR-FV10-020）。 |

### 8.4 集成测试 —— HTTP 多轮流程

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-143 | integration | 用同一个 `session_id` 连续发起两次 `/api/v2/chat/query`：第二次用代词指代第一次的主题，能得到正确答案（用一个固定的测试 LLM 替身，断言它收到的 prompt 里确实包含了预期的上下文）。 |
| TC-FV10-144 | integration | 同样的两个问题，第二次调用换成**不同**的 `session_id`，产生的是 AC-FV10-045 所描述的"无上下文"行为。 |
| TC-FV10-145 | integration | 经过若干轮之后调用会话历史接口，后续一次查询里实际注入的上下文恰好反映了配置的窗口大小，而不是全部历史。 |
| TC-FV10-150 | integration | 同一会话里，第一轮（`file_ids=["ufile_x"]`）之后第二轮（`file_ids=[]`）：第二轮的响应 `table_result_source` 反映的是文件/联合查询数据，来源是 `ufile_x`，对应 AC-FV10-048。 |
| TC-FV10-151 | integration | 第二轮显式传入 `file_ids=["ufile_y"]`（不同文件）：其响应来源是 `ufile_y`；之后第三轮 `file_ids=[]`，来源是 `ufile_y` 而不是 `ufile_x`，对应 AC-FV10-049。 |
| TC-FV10-152 | integration | 一个指代性追问（AC-FV10-051）触发的 LLM 调用集合（数量和调用点），跟一个结构等价的第一轮问题完全一致——不会多出一次专门的改写调用。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-051 | AC-FV10-044, AC-FV10-045 | TC-FV10-137, TC-FV10-138, TC-FV10-139 |
| FR-FV10-052 | AC-FV10-044 | TC-FV10-140, TC-FV10-141, TC-FV10-143 |
| FR-FV10-053 | AC-FV10-046 | TC-FV10-145 |
| FR-FV10-054 | AC-FV10-047 | —（纯前端；本 Spec 不定义后端测试用例） |
| FR-FV10-055 | AC-FV10-048, AC-FV10-049, AC-FV10-050 | TC-FV10-146, TC-FV10-147, TC-FV10-148, TC-FV10-150, TC-FV10-151 |
| FR-FV10-056 | AC-FV10-051 | TC-FV10-152 |
| NFR-FV10-018 | — | TC-FV10-142 |
| NFR-FV10-019 | AC-FV10-046 | TC-FV10-145 |
| NFR-FV10-020 | — | TC-FV10-149 |

## 10. 实现说明

- `resolve_effective_file_ids()`（第 6.4 节）必须在 `chat_query_v2` 靠前的位置调用一次，早于现有的 `if file_ids:` 路由分支——这个处理函数里下游所有用到 `file_ids` 的地方（校验、`_handle_file_data_chat_query`、审计记录）都必须使用**解析后**的值，而不是请求体里的原始字段，否则 FR-FV10-055 会悄悄退化成"除了路由判断本身之外，其他地方都没有继承"。
- `SessionFileContext` 是一个新的、按会话隔离的小型独立存储——刻意不通过扫描 `InMemoryQueryHistory.list_by_session()` 来推导，因为上下文窗口（FR-FV10-053，默认 5）跟"一个文件该保持多久处于'生效'状态"完全是两回事；一个会话完全可能围绕同一个文件聊上 20 轮，中间从未重新传过 `file_ids`。
- FR-FV10-056 在第 6.1/6.2 节之外没有引入新的数据契约——它约束的是"不要构建某个东西"（没有改写函数、没有额外的 LLM 调用）。TC-FV10-152 就是通过断言调用次数来真正强制这一点的测试，因为对于"不存在某个东西"这种情况，没有代码产物可以直接做单元测试。
- FR-FV10-054（前端线程渲染）没有后端测试用例，因为这纯粹是对现有聊天历史接口已经暴露的数据做渲染呈现；应该由前端/端到端测试覆盖，不在本 Spec 这套面向后端的测试用例编号体系里生造一个。
