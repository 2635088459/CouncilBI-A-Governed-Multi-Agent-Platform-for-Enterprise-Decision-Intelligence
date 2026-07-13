# 10.13 为非 SELECT 类 LLM 输出保留 Guardrail 拒绝原因

English version: [../../en/10-followups/13-guardrail-deny-reason-preservation.en.md](../../en/10-followups/13-guardrail-deny-reason-preservation.en.md)

## 1. 观察到的问题

一位分析师提问："Explain, step by step, how you calculated the churn rate for the enterprise segment in March 2026, including which tables/columns you pulled from — I need to include this in an audit trail."（请逐步说明你是怎么算出 2026 年 3 月企业客户群的流失率的，包括你用了哪些表/列——我需要把这个写进审计记录。）

返回结果被拦截，提示如下：

> **Query blocked — data modifications are not permitted**（查询被拦截——不允许修改数据）
> ChatBI is a read-only analytics platform. Requests to insert, update, delete, or otherwise modify data are automatically rejected by the security guardrail. If you have a legitimate data correction request, contact your data team directly.

这是一个纯粹的只读/解释类请求，完全没有任何写操作意图——根本没有什么"需要纠正"的数据。这条消息实际上误导了分析师对发生了什么、该怎么办的理解：这里根本不存在什么数据修改问题需要找数据团队处理；本文档的调查表明，真正的问题是这个编排器的 schema 里压根就没有 `churn`（流失率）相关的表，而且这个问题本身要求的是一段方法论叙述，而不是一个具体数字。

## 2. 已经具备的基础

### 2.1 拦截到底发生在哪一步

这个问题能通过 `_is_supported_question()`（`src/chatbi/orchestration/simple_orchestrator.py:822-854`）——它能匹配上"explain"等已支持的措辞——所以并不是在尝试生成 SQL 之前就被拒绝的。真正的拦截发生在**LLM 已经产出了它的输出之后**，由 `SqlStatementValidator.validate()`（`src/chatbi/governance/sql_validator.py:57-95`）来检查这个输出：

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
        SqlValidationViolationCode.NON_SELECT_STATEMENT,
        "Only SELECT statements are allowed.",
    )
```

这两个分支返回的是完全相同的 `SqlValidationViolationCode.NON_SELECT_STATEMENT`——一个对应的是真的命中了 `DROP`/`DELETE`/`UPDATE`/`INSERT`/`ALTER`/`TRUNCATE` 这类关键词（`_DANGEROUS_STATEMENT_PATTERN`，`sql_validator.py:10-13`——即便在一个只读 prompt 下这种情况本来就不太可能出现，但确实是真实的写操作意图),另一个对应的是**任何**不以 `"select "` 或 `"with "` 开头的文本——也就是模型没有生成 SQL，而是用大白话回答问题时的样子。这个函数一旦返回,下游没有任何一处能把这两种情况区分开。

### 2.2 为什么这个具体问题很可能命中的是第二个分支,而不是第一个

`_SQL_GENERATION_SYSTEM_PROMPT`（`simple_orchestrator.py:75-89`）是当问题没有被 `_build_sql_candidate` 那些硬编码的快捷方式匹配上时,才会用到的、带 schema 感知的兜底 prompt,它只描述了两张表:

```python
"Available tables:\n"
"revenue_by_month(month VARCHAR, revenue NUMERIC)\n"
"support_ticket_summary(month VARCHAR, product VARCHAR, severity VARCHAR, "
"ticket_count INTEGER, avg_resolution_hours NUMERIC)"
```

这里面没有 `churn` 表,没有 `enterprise_segment` 列,整个 schema 里没有任何跟流失率指标沾边的东西。要求它针对一份它根本看不到的数据"逐步解释"一个计算过程,同时又被明确告知只能回复"exactly one read-only SQL statement and nothing else"(只能回复一条读only SQL语句,不能有别的),模型根本没有正确的 SQL 可写——`simple_orchestrator.py:58-63` 已有的注释精确地记录了一个相关场景下的这种失败模式:"a real GPT model observed to do so wrapped its guess in prose and a markdown fence instead of bare SQL"（观察到真实的 GPT 模型在这种情况下会把它的猜测包在大白话和 markdown 代码块里,而不是纯 SQL）。一个要求"逐步解释"、又对应不上任何一张表的问题,比起一个只是问具体数字的问题,反而更容易产出大白话。

### 2.3 这个区分是如何在下游又被抹掉两次的

即便 `validate()` 确实返回了一个具体的违规代码,`SimpleSqlGuardrail._deny()`（`src/chatbi/governance/simple_guardrail.py:94-100`）也会把它扔掉,始终只发出同一个 `ErrorCode`:

```python
def _deny(self, trace_id: str, message: str) -> GuardrailResult:
    return GuardrailResult(
        decision=GuardrailDecision.DENY,
        trace_id=trace_id,
        error_code=ErrorCode.SQL_DENY_STATEMENT,
        message=message,
    )
```

`SqlValidationViolationCode` 的四个取值——`EMPTY_SQL`、`MULTIPLE_STATEMENTS`、`STRUCTURAL_RISK`、`NON_SELECT_STATEMENT`——全部会被折叠成同一个 `ErrorCode.SQL_DENY_STATEMENT`,唯一还能区分它们的只剩下那段自由文本 `message`,而 API 层根本没有任何地方去读取这段文本。

`api_error_for_warning()`（`src/chatbi/api/models.py:340-346`）接着又折叠了第三次:

```python
def api_error_for_warning(warning: WarningMessage) -> ApiErrorCode:
    if warning.code in {
        ErrorCode.SQL_DENY_STATEMENT,
        ErrorCode.SQL_DENY_OBJECT,
        ErrorCode.SQL_DENY_FUNCTION,
    }:
        return ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    ...
```

传到前端的时候,`SQL_DENY_STATEMENT`(这个问题实际走的路径)、`SQL_DENY_OBJECT`(访问了不允许的表)、`SQL_DENY_FUNCTION`(用了不允许的 SQL 函数)已经完全无法区分——三种结构上完全不同的拒绝原因,共用同一个 API 错误码 `SQL_GUARDRAIL_BLOCKED`。

前端（`frontend/src/App.tsx:1143-1154`）随后为这一个错误码硬编码了一条固定消息:

```tsx
errorCode === "SQL_GUARDRAIL_BLOCKED" ? (
  <div className="answer-blocked">
    <div className="blocked-icon">⊘</div>
    <div className="blocked-body">
      <p className="blocked-title">Query blocked — data modifications are not permitted</p>
      <p className="blocked-desc">
        ChatBI is a read-only analytics platform. Requests to insert, update, delete,
        or otherwise modify data are automatically rejected by the security guardrail.
        If you have a legitimate data correction request, contact your data team directly.
      </p>
    </div>
  </div>
```

对于真的命中 `_DANGEROUS_STATEMENT_PATTERN` 的情况,这条消息是准确的。但对于这个问题实际、也更可能走的那条路径——模型之所以用大白话回答,是因为压根没有流失率表可查——这条消息就是单纯地说错了:根本没有发生任何修改数据的尝试,"联系你的数据团队"这个建议更是完全指错了方向。

## 3. 设计:把"写了一条真实语句"和"根本没写出查询"区分开

§2.1 里被混为一谈的两个分支,本质上是两种不同的失败模式,应该对应两个不同的 `SqlValidationViolationCode` 取值:

```python
class SqlValidationViolationCode(StrEnum):
    EMPTY_SQL = "empty_sql"
    MULTIPLE_STATEMENTS = "multiple_statements"
    STRUCTURAL_RISK = "structural_risk"
    NON_SELECT_STATEMENT = "non_select_statement"       # 不变:确实命中了真实的 DML/DDL 关键词
    UNRECOGNIZED_QUERY_OUTPUT = "unrecognized_query_output"  # 新增:既没有 SELECT/WITH 前缀,也没有命中危险关键词
```

`SqlStatementValidator.validate()` 的两处判断逻辑本身不变,只是上报的结果不同:

```python
if _DANGEROUS_STATEMENT_PATTERN.search(normalized_sql):
    return self._deny(
        normalized_sql,
        SqlValidationViolationCode.NON_SELECT_STATEMENT,   # 不变——真实的写操作意图
        "Only SELECT statements are allowed.",
    )

if not normalized_sql.lower().startswith(_ALLOWED_STATEMENT_PREFIXES):
    return self._deny(
        normalized_sql,
        SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT,  # 新增
        "The model's output was not a single read-only query.",
    )
```

## 4. 设计:把这个区分再往下游多传两层

`ErrorCode`（`src/chatbi/core/contracts.py`）新增一个取值 `SQL_DENY_UNRECOGNIZED_OUTPUT`,跟已有的 `SQL_DENY_STATEMENT`/`SQL_DENY_OBJECT`/`SQL_DENY_FUNCTION` 并列。`SimpleSqlGuardrail._deny()` 被拆开,让调用方——它本来就已经拿到了 `SqlValidationResult` 和它的 `violation_code`——自己去选正确的 `ErrorCode`,而不是让 `_deny()` 内部写死一个:

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

`api_error_for_warning()`（`src/chatbi/api/models.py:340-346`）新增一个对应分支,映射到一个新的 `ApiErrorCode.SQL_NOT_QUERYABLE`,跟 `SQL_GUARDRAIL_BLOCKED` 保持区分:

```python
def api_error_for_warning(warning: WarningMessage) -> ApiErrorCode:
    if warning.code is ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT:
        return ApiErrorCode.SQL_NOT_QUERYABLE
    if warning.code in {
        ErrorCode.SQL_DENY_STATEMENT,
        ErrorCode.SQL_DENY_OBJECT,
        ErrorCode.SQL_DENY_FUNCTION,
    }:
        return ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    ...
```

前端（`frontend/src/App.tsx:1143-1154`）为 `SQL_NOT_QUERYABLE` 新增一个并列分支,文案如实描述发生了什么,而不是暗示存在一次写入尝试:

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
  ...
```

对于报告里那个问题,分析师现在看到的消息能正确指出实际的缺口(没有对应的表/指标,或者这种问题的表述形式,只读 SQL 生成器没法转成 SQL),而不是被告知去联系数据团队处理一次根本没有发生过的数据修改请求。

## 5. 验证

[Spec FV10.13](../../../../spec/final-version/zh-CN/10-followups/13-guardrail-deny-reason-preservation.spec.zh-CN.md) 在实现之前就把上面第 3、4 节转化成了需求、验收标准和测试用例。大致包括:

- `SqlStatementValidator.validate()` 的单元测试(`tests/test_sql_validator.py`):一条命中 `_DANGEROUS_STATEMENT_PATTERN` 的语句(比如 `"UPDATE revenue_by_month SET revenue = 0"`)仍然返回 `NON_SELECT_STATEMENT`;一段没有 SELECT/WITH 前缀、也没有命中任何危险关键词的大白话(比如 `"I don't have a churn table to query."`)返回新增的 `UNRECOGNIZED_QUERY_OUTPUT`。
- `SimpleSqlGuardrail.check()` 的单元测试(`tests/test_simple_guardrail.py`):上面两种违规代码分别产出正确、可区分的 `ErrorCode`。
- `api_error_for_warning()` 的单元测试(`tests/test_api_models.py`):`SQL_DENY_UNRECOGNIZED_OUTPUT` 映射到 `SQL_NOT_QUERYABLE`;原有三个错误码依然不变地映射到 `SQL_GUARDRAIL_BLOCKED`。
- 一份 HTTP 层测试(`tests/test_v2_chat_query_http.py`),让一个 LLM 桩针对一个 schema 不匹配的问题返回大白话,断言响应的 `code` 是 `SQL_NOT_QUERYABLE`。这次测试还暴露出一处 Spec 数据契约里最初没有列出的地方:`status_code_for_envelope()`(`http.py:495-506`)对这个新代码完全没有对应分支,会悄悄落到默认的 `200`,而这个响应的 `error` 字段其实非空——已修正为 `400`,跟 `REQ_INVALID_ARGUMENT` 已经在用的状态码一致,跟既有的 `SQL_GUARDRAIL_BLOCKED → 403` 并列。
- 整个项目测试套件(1396 个测试,不含本项目自己的惯例早已记录为无关的、既有的 Postgres 凭据类和前端构建产物类失败)全部通过。

## 6. 已知限制——本次刻意不解决

- **`EMPTY_SQL`、`MULTIPLE_STATEMENTS`、`STRUCTURAL_RISK` 依然维持映射到 `SQL_DENY_STATEMENT`/`SQL_GUARDRAIL_BLOCKED` 不变。**报告里的这个问题实际命中的不是这三者中的任何一个,而且它们也不像 `NON_SELECT_STATEMENT` 跟"大白话"混在一起那样,携带同样具体的"听起来像写操作"的措辞问题——现有那条偏 DML 口吻的消息对它们来说不够精确,但不像本次这样是彻底说反了。要把这四种代码全部逐一拆开,是一次范围更大、需要单独立项的重构。
- **这不会让没有对应表的问题真的能被回答出来。**流失率相关的问题依然答不出来——这份设计只是让*报告出来的原因*变得准确。要真正回答这个问题,需要扩展 `_SQL_GENERATION_SYSTEM_PROMPT` 的 schema(超出本次范围;得先真的有一张流失率相关的表/视图存在),或者做一条独立的"我没有这份数据"应答路径,本文档都没有提出这两者中的任何一个。
- **新增的前端文案是通用的。**它不会尝试告诉分析师具体*缺了哪张表或哪个指标*——在这一层,`SqlValidationResult.message` 本身没有任何 schema 感知能力可用。要给出更具体的消息,需要把 schema 缺口信息从 SQL 生成实际失败的那个地方一路往前传,这是一个比本 Spec 范围更大的改动。

## 7. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-087 | 当归一化后的 SQL 文本既不以允许的语句前缀开头、也没有命中 `_DANGEROUS_STATEMENT_PATTERN` 时,`SqlStatementValidator.validate()` 必须返回新增的 `SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT`;当命中 `_DANGEROUS_STATEMENT_PATTERN` 时,必须继续返回 `NON_SELECT_STATEMENT`。 | 已实现 |
| FR-FV10-088 | `SimpleSqlGuardrail.check()` 必须把 `SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT` 映射到新增的 `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT`,并与 `ErrorCode.SQL_DENY_STATEMENT` 保持区分。 | 已实现 |
| FR-FV10-089 | `api_error_for_warning()` 必须把 `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT` 映射到新增的 `ApiErrorCode.SQL_NOT_QUERYABLE`,并与 `ApiErrorCode.SQL_GUARDRAIL_BLOCKED` 保持区分。 | 已实现 |
| FR-FV10-090 | 前端必须为 `SQL_NOT_QUERYABLE` 渲染一条独立的消息,且这条消息不得把该请求描述成一次数据修改尝试。 | 已实现 |
| NFR-FV10-030 | 本次改动不得改变真实命中 `_DANGEROUS_STATEMENT_PATTERN`、`SQL_DENY_OBJECT` 拒绝、或 `SQL_DENY_FUNCTION` 拒绝时产出的 `ErrorCode`/`ApiErrorCode`/前端消息。 | 已实现 |

## 8. 现状:已修复并验证

通过直接阅读这个问题的响应实际经过的"校验 → guardrail → API 错误码 → 前端"这条完整链路的代码,确认了信息在三个折叠点(§2.1、§2.3)分别丢失,而不是只依赖一次实盘复现。按本项目一贯的 SDD+TDD 顺序先写设计、后写 Spec:[Spec FV10.13](../../../../spec/final-version/zh-CN/10-followups/13-guardrail-deny-reason-preservation.spec.zh-CN.md) 把上面第 3、4 节转化成了正式的需求、验收标准和测试计划,然后两者都已实现。修复涉及 `src/chatbi/governance/sql_validator.py`、`src/chatbi/governance/simple_guardrail.py`、`src/chatbi/core/contracts.py`、`src/chatbi/api/models.py`、`src/chatbi/api/http.py`(第 5 节提到的 `status_code_for_envelope()` 新增分支)以及 `frontend/src/App.tsx`;`tests/test_sql_validator.py`、`tests/test_simple_guardrail.py`、`tests/test_api_models.py`、`tests/test_v2_chat_query_http.py` 里新增了对应测试。
