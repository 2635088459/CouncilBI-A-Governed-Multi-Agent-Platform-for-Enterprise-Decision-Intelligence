# Spec FV10.13:为非 SELECT 类 LLM 输出保留 Guardrail 拒绝原因

English version: [../../en/10-followups/13-guardrail-deny-reason-preservation.spec.en.md](../../en/10-followups/13-guardrail-deny-reason-preservation.spec.en.md)

来源设计文档:
- [10.13 为非 SELECT 类 LLM 输出保留 Guardrail 拒绝原因](../../../../system_design/final-version/zh-CN/10-followups/13-guardrail-deny-reason-preservation.zh-CN.md)
- [Spec FV-10: 用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)(平级 Spec;本 Spec 的需求跟文件上传功能本身无关——它修订的这条 guardrail 链路是共享基础设施,文件类问题和非文件类问题都会走这条路)

本 Spec 按本项目一贯的 SDD+TDD 顺序,**先写 Spec、再实现**。下面每一条功能需求都至少对应一条验收标准和一条测试用例;每一条测试用例都能追溯回一条需求。测试用例先针对实现之前的代码确认跑出了**红灯**,实现完成之后再确认跑出**绿灯**——第 10 节记录了其中一条需求(AC-FV10-103/TC-FV10-215)本项目测试套件目前没有现成的自动化手段去验证,以及实际是怎么验证的。

---

## 1. 目的

一个纯只读、解释类的问题("请逐步解释你是怎么算出流失率的……")被拦截,提示信息却声称这次请求试图修改数据。完整阅读这次请求走过的链路——`SqlStatementValidator.validate()` → `SimpleSqlGuardrail._deny()` → `api_error_for_warning()` → 前端的 `SQL_GUARDRAIL_BLOCKED` 分支——可以看到,"模型输出里确实包含真实的 DML/DDL 关键词"和"模型输出只是因为别的原因不是一条 SELECT 语句"这两者的区分,在 `validate()` 的两个分支里其实是被正确计算出来过一次的,但紧接着被连续丢弃了三次:两个分支返回的都是同一个 `SqlValidationViolationCode.NON_SELECT_STATEMENT`;`SimpleSqlGuardrail._deny()` 把所有违规代码都映射到同一个 `ErrorCode.SQL_DENY_STATEMENT`;`api_error_for_warning()` 又把 `SQL_DENY_STATEMENT` 和另外两个毫不相关的拒绝原因(`SQL_DENY_OBJECT`、`SQL_DENY_FUNCTION`)一起映射到同一个 `ApiErrorCode.SQL_GUARDRAIL_BLOCKED`。

本 Spec 新增一个违规代码、一个 `ErrorCode`、一个 `ApiErrorCode`——把"命中危险关键词"和"模型输出的不是 SQL"这一个区分,原样贯穿这四层,让前端能针对这次报告的场景展示准确的消息。

## 2. 范围

**范围内:**
- 新增 `SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT` 取值,当 `SqlStatementValidator.validate()` 最后一道前缀检查没有命中任何危险语句关键词时返回它。
- 新增 `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT` 取值,`SimpleSqlGuardrail` 的拒绝构造逻辑根据校验器的违规代码,在它和已有的 `ErrorCode.SQL_DENY_STATEMENT` 之间做选择。
- 新增 `ApiErrorCode.SQL_NOT_QUERYABLE` 取值,以及 `api_error_for_warning()` 里对应的分支。
- 在 `frontend/src/App.tsx` 中为 `SQL_NOT_QUERYABLE` 新增一个前端消息分支。

**范围外:**
- `SqlValidationViolationCode.EMPTY_SQL`、`MULTIPLE_STATEMENTS`、`STRUCTURAL_RISK`——这三者继续不变地映射到 `ErrorCode.SQL_DENY_STATEMENT`/`ApiErrorCode.SQL_GUARDRAIL_BLOCKED`;具体原因见来源设计文档第 6 节。
- 不会让没有对应表或指标的问题真的能生成出 SQL——本 Spec 只让报告问题*显示出来的原因*变得准确,不会让这个问题底层真正可答。
- 新前端消息里不包含任何 schema 相关的具体细节(比如指出缺了哪张表)——在这一层,`SqlValidationResult` 没有任何 schema 感知能力。
- 不改动 `FederatedQueryAgent` 自己独立的 guardrail 路径(`src/chatbi/agents/federated_query_agent.py` 里的 `_guardrail_check()`,由 `find_blocked_statement()` 支撑)——这是跟 `SimpleSqlGuardrail`/`SqlStatementValidator` 完全不同的另一套 guardrail 实现,本次不涉及。

## 3. 参与者

复用父 Spec FV-10 第 3 节定义的参与者,不新增参与者。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-087 | 当归一化后的 SQL 文本既不以允许的语句前缀(`select `/`with `)开头、也没有命中 `_DANGEROUS_STATEMENT_PATTERN` 时,`SqlStatementValidator.validate()` 必须返回 `SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT`。只要命中了 `_DANGEROUS_STATEMENT_PATTERN`,不管前缀是什么,都必须继续返回 `SqlValidationViolationCode.NON_SELECT_STATEMENT`。 |
| FR-FV10-088 | 当 `SqlStatementValidator.validate()` 的结果 `violation_code == SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT` 时,`SimpleSqlGuardrail.check()` 构造出的拒绝 `GuardrailResult` 必须使用 `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT`;对于其余每一种违规代码(`EMPTY_SQL`、`MULTIPLE_STATEMENTS`、`STRUCTURAL_RISK`、`NON_SELECT_STATEMENT`),必须继续不变地使用 `ErrorCode.SQL_DENY_STATEMENT`。 |
| FR-FV10-089 | `api_error_for_warning()` 必须把 `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT` 映射到新增的 `ApiErrorCode.SQL_NOT_QUERYABLE`。必须继续把 `ErrorCode.SQL_DENY_STATEMENT`、`ErrorCode.SQL_DENY_OBJECT`、`ErrorCode.SQL_DENY_FUNCTION` 不变地映射到 `ApiErrorCode.SQL_GUARDRAIL_BLOCKED`。 |
| FR-FV10-090 | 前端(`frontend/src/App.tsx`)必须为 `errorCode === "SQL_NOT_QUERYABLE"` 渲染一条独立的错误消息,其标题和正文都不得声称或暗示该请求试图插入、更新或删除数据。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-030 | 本 Spec 的改动不得改变以下场景产出的 `ErrorCode`、`ApiErrorCode` 或前端消息:(a) SQL 文本同时命中 `_DANGEROUS_STATEMENT_PATTERN` 且以允许的前缀开头(按 FR-FV10-087,`_DANGEROUS_STATEMENT_PATTERN` 不管前缀是什么都会被优先检查的边界情形);(b) `ErrorCode.SQL_DENY_OBJECT` 拒绝(访问了不允许的表);(c) `ErrorCode.SQL_DENY_FUNCTION` 拒绝(用了不允许的 SQL 函数)。 |

## 6. 数据契约

### 6.1 `SqlValidationViolationCode` — `src/chatbi/governance/sql_validator.py`

```python
class SqlValidationViolationCode(StrEnum):
    EMPTY_SQL = "empty_sql"
    MULTIPLE_STATEMENTS = "multiple_statements"
    STRUCTURAL_RISK = "structural_risk"
    NON_SELECT_STATEMENT = "non_select_statement"
    UNRECOGNIZED_QUERY_OUTPUT = "unrecognized_query_output"
```

`SqlStatementValidator.validate()` 最后两处判断变为:

```python
if _DANGEROUS_STATEMENT_PATTERN.search(normalized_sql):
    return self._deny(
        normalized_sql,
        SqlValidationViolationCode.NON_SELECT_STATEMENT,
        "Only SELECT statements are allowed.",
    )

if not normalized_sql.lower().startswith(_ALLOWED_STATEMENT_PREFIXES):
    return self._deny(
        normalized_sql,
        SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT,
        "The model's output was not a single read-only query.",
    )
```

### 6.2 `ErrorCode` — `src/chatbi/core/contracts.py`

```python
class ErrorCode(StrEnum):
    ...
    SQL_DENY_STATEMENT = "SQL_DENY_STATEMENT"
    SQL_DENY_UNRECOGNIZED_OUTPUT = "SQL_DENY_UNRECOGNIZED_OUTPUT"
    ...
```

### 6.3 `SimpleSqlGuardrail` — `src/chatbi/governance/simple_guardrail.py`

```python
def check(self, sql_text: str, request: QueryRequest, trace_id: str) -> GuardrailResult:
    validation = self._statement_validator.validate(sql_text)
    if not validation.passed:
        result = self._deny_for_violation(trace_id, validation)
        return self._record_decision(sql_text, request, result)
    ...

def _deny_for_violation(
    self, trace_id: str, validation: SqlValidationResult
) -> GuardrailResult:
    error_code = (
        ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT
        if validation.violation_code is SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT
        else ErrorCode.SQL_DENY_STATEMENT
    )
    return GuardrailResult(
        decision=GuardrailDecision.DENY,
        trace_id=trace_id,
        error_code=error_code,
        message=validation.message or "SQL was denied.",
    )
```

原有的 `_deny(self, trace_id, message)` 辅助方法被移除,改用 `_deny_for_violation`——后者接收完整的 `SqlValidationResult`,而不是一个裸的消息字符串;`check()` 内部所有原本调用 `_deny()` 的地方都改为调用 `_deny_for_violation()`。

### 6.4 `ApiErrorCode` 和 `api_error_for_warning()` — `src/chatbi/api/models.py`

```python
class ApiErrorCode(StrEnum):
    ...
    SQL_GUARDRAIL_BLOCKED = "SQL_GUARDRAIL_BLOCKED"
    SQL_NOT_QUERYABLE = "SQL_NOT_QUERYABLE"
    ...

def api_error_for_warning(warning: WarningMessage) -> ApiErrorCode:
    if warning.code is ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT:
        return ApiErrorCode.SQL_NOT_QUERYABLE
    if warning.code in {
        ErrorCode.SQL_DENY_STATEMENT,
        ErrorCode.SQL_DENY_OBJECT,
        ErrorCode.SQL_DENY_FUNCTION,
    }:
        return ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    if warning.code is ErrorCode.QUERY_TIMEOUT:
        return ApiErrorCode.QUERY_TIMEOUT
    if warning.code is ErrorCode.AGENT_PARTIAL_FAILURE:
        return ApiErrorCode.AGENT_PARTIAL_FAILURE
    if warning.code is ErrorCode.UNSUPPORTED_QUESTION:
        return ApiErrorCode.REQ_INVALID_ARGUMENT
    return ApiErrorCode.INTERNAL_ERROR
```

### 6.5 前端消息分支 — `frontend/src/App.tsx`

```tsx
errorCode === "SQL_NOT_QUERYABLE" ? (
  <div className="answer-blocked answer-blocked--warn">
    <div className="blocked-icon">⚠</div>
    <div className="blocked-body">
      <p className="blocked-title">Can't generate a query for this question</p>
      <p className="blocked-desc">
        This question doesn't match a read-only query we can run against the
        available data. Try rephrasing it as a specific data question, or
        check that the data you're asking about exists in a connected table.
      </p>
    </div>
  </div>
) : errorCode === "SQL_GUARDRAIL_BLOCKED" ? (
  /* 不变 */
  ...
```

新分支作为并列条件,放在现有 `SQL_GUARDRAIL_BLOCKED` 判断之前(`App.tsx:1143` 起同一条条件链上),复用紧挨在下面的 `VALIDATION_ERROR`、`REQ_INVALID_ARGUMENT` 分支已经在用的 `answer-blocked--warn` 样式,而不是留给真实 guardrail 拒绝场景专用的 `⊘`/警示红样式。

### 6.6 HTTP 状态码 — `src/chatbi/api/http.py`(实现过程中发现的补充——见第 10 节)

```python
def status_code_for_envelope(envelope: ApiEnvelope) -> int:
    ...
    if envelope.code is ApiErrorCode.SQL_GUARDRAIL_BLOCKED:
        return 403
    if envelope.code is ApiErrorCode.SQL_NOT_QUERYABLE:
        return 400
    return 200
```

这不是第 6 节最初列出的数据契约的一部分——`status_code_for_envelope()` 对它不认识的任何错误码都没有对应分支,所以如果没有这处补充,`SQL_NOT_QUERYABLE` 响应会返回 HTTP `200`,而这个响应的 `error` 字段其实非空,是一个内部自相矛盾的信封。`400` 跟这个函数已有的 `REQ_INVALID_ARGUMENT` 映射保持一致——这是"请求本身的表述没法被满足"这一类情形现有最贴近的先例,而不是一次安全层面的拒绝。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-096 | `SqlStatementValidator().validate("UPDATE revenue_by_month SET revenue = 0")` 返回 `violation_code == SqlValidationViolationCode.NON_SELECT_STATEMENT`(与当前行为一致,不变)。 |
| AC-FV10-097 | `SqlStatementValidator().validate("I don't have a churn table to query against.")` 返回 `violation_code == SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT`。 |
| AC-FV10-098 | `SimpleSqlGuardrail().check(sql_text="UPDATE revenue_by_month SET revenue = 0", ...)` 返回的 `GuardrailResult` 中 `error_code == ErrorCode.SQL_DENY_STATEMENT`(不变)。 |
| AC-FV10-099 | `SimpleSqlGuardrail().check(sql_text="I don't have a churn table to query against.", ...)` 返回的 `GuardrailResult` 中 `error_code == ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT`。 |
| AC-FV10-100 | `api_error_for_warning(WarningMessage(code=ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT, ...))` 返回 `ApiErrorCode.SQL_NOT_QUERYABLE`。 |
| AC-FV10-101 | 分别用 `ErrorCode.SQL_DENY_STATEMENT`、`ErrorCode.SQL_DENY_OBJECT`、`ErrorCode.SQL_DENY_FUNCTION` 调用 `api_error_for_warning()`,三者依然都返回 `ApiErrorCode.SQL_GUARDRAIL_BLOCKED`(不变)。 |
| AC-FV10-102 | `POST /api/v2/chat/query`,配合一个被设置为返回大白话(没有 SELECT/WITH 前缀,也没有危险关键词)的 LLM 桩——复现报告里那个流失率审计追溯问题很可能触发的模型输出——返回的响应 `code` 应为 `"SQL_NOT_QUERYABLE"`(而不是 `"SQL_GUARDRAIL_BLOCKED"`),HTTP 状态码应为 `400`(第 6.6 节)。 |
| AC-FV10-103 | 前端在 `errorCode === "SQL_NOT_QUERYABLE"` 时渲染第 6.5 节的消息(标题:"Can't generate a query for this question");在 `errorCode === "SQL_GUARDRAIL_BLOCKED"` 时,继续不变地渲染既有第 2.3 节的消息(标题:"Query blocked — data modifications are not permitted")。 |

## 8. 测试计划

### 8.1 单元测试 — `SqlStatementValidator`

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-208 | unit | `validate("UPDATE revenue_by_month SET revenue = 0")` → `NON_SELECT_STATEMENT`(AC-FV10-096)。实现为 `tests/test_sql_validator.py::test_sql_statement_validator_denies_dangerous_statement_as_non_select_statement`。 |
| TC-FV10-209 | unit | `validate("I don't have a churn table to query against.")` → `UNRECOGNIZED_QUERY_OUTPUT`(AC-FV10-097)。实现为 `test_sql_statement_validator_denies_prose_output_as_unrecognized_query_output`。 |

### 8.2 单元测试 — `SimpleSqlGuardrail`

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-210 | unit | `check()` 传入一条真实的危险语句 SQL 文本 → `error_code == SQL_DENY_STATEMENT`(AC-FV10-098)。实现为 `tests/test_simple_guardrail.py::test_guardrail_rejects_dangerous_statement_with_sql_deny_statement`。 |
| TC-FV10-211 | unit | `check()` 传入大白话 SQL 文本 → `error_code == SQL_DENY_UNRECOGNIZED_OUTPUT`(AC-FV10-099)。实现为 `test_guardrail_rejects_prose_output_with_sql_deny_unrecognized_output`。 |

### 8.3 单元测试 — `api_error_for_warning()`

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-212 | unit | `api_error_for_warning(WarningMessage(code=SQL_DENY_UNRECOGNIZED_OUTPUT))` → `SQL_NOT_QUERYABLE`(AC-FV10-100)。实现为 `tests/test_api_models.py::test_api_error_for_warning_maps_unrecognized_output_to_sql_not_queryable`。 |
| TC-FV10-213 | regression | `api_error_for_warning()` 针对 `SQL_DENY_STATEMENT`、`SQL_DENY_OBJECT`、`SQL_DENY_FUNCTION` 分别依然返回 `SQL_GUARDRAIL_BLOCKED`(AC-FV10-101)。实现为 `test_api_error_for_warning_still_maps_guardrail_denials_to_sql_guardrail_blocked`(参数化测试)。 |

### 8.4 集成测试 — HTTP 与前端

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-214 | integration (HTTP) | `POST /api/v2/chat/query`,配合一个针对无对应 schema 表的问题返回大白话输出的 LLM 桩,返回 `code == "SQL_NOT_QUERYABLE"`、HTTP 状态码 `400`(AC-FV10-102;`400` 这个映射是实现过程中对第 6 节的一处补充——见第 10 节)。实现为 `tests/test_v2_chat_query_http.py::test_v2_chat_query_with_non_queryable_model_output_returns_sql_not_queryable`。 |
| TC-FV10-215 | frontend | 一份组件/story 测试,断言 `SQL_NOT_QUERYABLE` 分支渲染出 "Can't generate a query for this question";另一份并列测试确认 `SQL_GUARDRAIL_BLOCKED` 分支的渲染结果跟本 Spec 实现之前逐字/逐像素一致(AC-FV10-103)。**没有实现成自动化测试**——本项目目前没有针对 `App.tsx` 的组件级或快照测试基础设施可以扩展(它既有的 `SQL_GUARDRAIL_BLOCKED` 分支同样也没有专门的测试);第 10 节记录了 AC-FV10-103 实际是怎么验证的。 |

### 8.5 回归测试

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-216 | regression | `tests/test_sql_validator.py` 中所有覆盖 `EMPTY_SQL`、`MULTIPLE_STATEMENTS`、`STRUCTURAL_RISK` 的既有测试保持不变、继续通过——本 Spec 不涉及这三个违规代码及其下游 `ErrorCode`/`ApiErrorCode` 映射(NFR-FV10-030)。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-087 | AC-FV10-096, AC-FV10-097 | TC-FV10-208, TC-FV10-209 |
| FR-FV10-088 | AC-FV10-098, AC-FV10-099 | TC-FV10-210, TC-FV10-211 |
| FR-FV10-089 | AC-FV10-100, AC-FV10-101 | TC-FV10-212, TC-FV10-213 |
| FR-FV10-090 | AC-FV10-102, AC-FV10-103 | TC-FV10-214, TC-FV10-215 |
| NFR-FV10-030 | AC-FV10-096, AC-FV10-101 | TC-FV10-208, TC-FV10-213, TC-FV10-216 |

## 10. 实现注记

- 本 Spec 是在实现之前写的,而且在第 6 节的改动落地之前,已经确认过 TC-FV10-208 到 TC-FV10-214 针对实现之前的代码,会因为预期的原因失败——`UNRECOGNIZED_QUERY_OUTPUT`、`SQL_DENY_UNRECOGNIZED_OUTPUT`、`SQL_NOT_QUERYABLE` 当时都还不存在。
- 第 6.3 节移除了 `SimpleSqlGuardrail._deny(self, trace_id, message)`,而不是在它旁边再加一个新方法——因为 `check()` 内部原来的调用点都需要同样根据 `validation.violation_code` 做分支判断;如果把旧的辅助方法留着不用、或者只在部分调用点替换,就会重新引入本 Spec 本来就是为了关闭的那种"悄悄被折叠丢弃"的风险。`check()` 现在只有一处调用点,用的是 `_deny_for_violation()`。
- **第 6 节最初的写法漏掉了一处契约**,是在实现 TC-FV10-214 时发现的:`status_code_for_envelope()`(`src/chatbi/api/http.py:495-506`)负责把 `ApiErrorCode` 映射成 HTTP 状态码,但对新增的 `SQL_NOT_QUERYABLE` 完全没有对应分支,会悄悄落到它默认的 `return 200`,而这个响应的 `error` 字段其实非空。已新增 `if envelope.code is ApiErrorCode.SQL_NOT_QUERYABLE: return 400`,跟这个函数里既有的 `SQL_GUARDRAIL_BLOCKED → 403` 映射并列——`400` 跟这个文件已经在用的 `REQ_INVALID_ARGUMENT` 状态码一致,这也是"请求本身的表述没法被满足"这一类情形,而不是一次安全层面的拒绝。
- TC-FV10-214 的 LLM 桩,针对一个 schema 不匹配的问题能稳定产出大白话而不是 SQL,依据的是来源设计文档第 2.2 节的推理(一个"逐步解释"类问题,针对一个 `_SQL_GENERATION_SYSTEM_PROMPT` schema 里根本没有的指标):这个桩(`_ProseForSqlGenerationLLMClient`)专门针对 `task_type == "sql_generation"` 的请求返回大白话,其他情况返回一个无害的字符串,通过 `SimpleOrchestrator(llm_client=...)`/`ChatBIApplication(orchestrator=...)` 传给 `create_app(application=...)` 接入——用一个确定性的桩,而不是一次真实的模型调用,才能让这条测试在 CI 里稳定可靠。
- **AC-FV10-103/TC-FV10-215(前端渲染断言)没有实现成自动化测试。**本项目目前没有针对 `frontend/src/App.tsx` 的组件级或快照测试基础设施——它既有的 `SQL_GUARDRAIL_BLOCKED` 分支(第 2.3 节)同样也没有专门的测试,只有 `tests/test_frontend_view_models.py`/`tests/test_frontend_evaluation_component_props.py` 这类断言无关 view-model 结构的 Python 测试,不是断言渲染出来的 JSX 文本。AC-FV10-103 改为通过以下方式验证:(a) 第 6.5 节的 JSX 改动加入后,`npx tsc --noEmit` 干净地通过,确认没有类型或语法层面的回归;(b) 直接代码审查,确认新的 `SQL_NOT_QUERYABLE` 分支是紧接在既有 `SQL_GUARDRAIL_BLOCKED` 分支之前的一个并列 `? :` 分支,而 `SQL_GUARDRAIL_BLOCKED` 分支本身逐字未改。后续可以考虑补一套轻量级的前端测试基础设施,把这一步变成真正的自动化检查——这超出了本 Spec 第 2 节已经声明的范围。
