# Spec Review Gate: Verifiable, Small-Step, TDD-Ready

本文档用于审查 `spec/version1/*.spec.md` 是否真的能被人和 AI 承接实现。审查目标不是判断规格“看起来像不像对的”，而是判断它是否能被验证、能被小步实现、能进入 TDD 红绿循环。

## 1. 审查结论

当前 10 份 spec 已经有 SDD/TDD 骨架：范围、编号需求、验收标准、测试计划和追踪矩阵都存在。

但它们现在还不能直接作为严格实现门禁，原因是：

- 不是每条 FR/NFR 都进入了 Traceability Matrix。
- 多数 Contract 还是字段列表，不是可执行 schema 或类型定义。
- 部分要求使用了不可判定词，例如 `stable`、`controllable`、`normal load`、`plausible`、`full context`、`correct`、`safe message`。
- 部分性能指标有阈值，但缺少测试环境、数据规模、并发模型和统计窗口。
- 部分业务语义有例子，但没有固定 benchmark fixture，因此测试结果容易变成主观判断。

因此，当前状态应标记为：

```text
Spec status: Draft, not implementation-gate ready
Required next state: Verifiable Draft
```

## 2. 审规格的硬规则

每条规格必须满足以下条件，否则不能进入实现：

| Rule | Pass condition | Machine gate |
|---|---|---|
| One requirement, one verifier | 每个 `FR-*` / `NFR-*` 至少映射到一个 `AC-*` 和一个 `TC-*` | Traceability Matrix 检查 |
| Typed contracts | 每个 API / agent / module contract 有 Pydantic model、TypedDict、dataclass、OpenAPI schema 或 JSON Schema | pyright / schema validation |
| Deterministic fixture | 行为测试有固定输入、固定 seed data、固定期望输出或可判定谓词 | pytest |
| Quantified NFR | 性能、准确率、覆盖率、错误率有阈值、窗口、样本集和运行环境 | pytest-benchmark / load test |
| Negative case required | 每个安全、权限、错误处理规则至少有一个拒绝路径测试 | pytest |
| No subjective language | `good`、`clear`、`safe`、`stable`、`plausible` 等词必须改写为可断言条件 | spec lint / review |
| One rollback unit | 每次实现只覆盖一个端点、一个 agent step、一个 policy rule 或一个 schema | PR checklist |

不可验证的要求视为没有要求。例如：

```text
Bad: Performance must not be too slow.
Good: /api/v1/chat/query P95 latency MUST be <= 8s over 500 requests, 20 concurrent users, seeded Postgres dataset v1, with mock LLM provider.
```

## 3. TDD 验收三层

### Layer 1: pyright static gate

目标：不用运行测试就拦住类型错误、缺失导入、参数不匹配、字段名不一致。

通过条件：

```text
pyright: 0 errors
```

每个 contract 必须能落到类型约束：

- API request / response: Pydantic model or OpenAPI schema
- Agent input / output: TypedDict, dataclass, or Pydantic model
- Error code: Literal / Enum
- Role / policy level / status: Literal / Enum
- Trace and audit fields: required typed fields

### Layer 2: pytest full suite

目标：spec 的每条规则和边界条件都变成测试。

通过条件：

```text
pytest: all tests green
```

最低测试映射：

- `FR-*`: unit or integration test
- `NFR-*`: benchmark, load, compliance, or property test
- Security rule: allow case and deny case
- Replay rule: original input and replay output equality assertion
- Audit rule: action result and audit record both asserted

### Layer 3: example plus human acceptance

目标：机器能判的都已经判完，人只看机器难判的部分。

人工验收只看三件事：

- 调用方式是否简洁。
- 错误提示是否清晰、可行动。
- 业务语义是否真的符合产品预期。

人工验收不能替代 Layer 1 和 Layer 2。

## 4. 当前 Spec 覆盖缺口

以下统计来自对 `spec/version1/*.spec.md` 的 ID 和 Traceability Matrix 抽查。每个缺失项都必须补一个 AC 和 TC，或删除/降级该要求。

| Spec | Missing traceability |
|---|---|
| 01 Overall Architecture | `FR-01-002`, `FR-01-006`, `FR-01-007`, `NFR-01-001`, `NFR-01-002`, `NFR-01-003`, `NFR-01-005`, `NFR-01-006` |
| 02 Agent Orchestration | `FR-02-002`, `FR-02-004`, `FR-02-005`, `FR-02-007`, `NFR-02-002`, `NFR-02-004` |
| 03 Semantic Layer and NL2SQL | `FR-03-001`, `FR-03-006`, `FR-03-008`, `NFR-03-001`, `NFR-03-002` |
| 04 SQL Guardrail and Governance | `FR-04-002`, `FR-04-007`, `NFR-04-001`, `NFR-04-003` |
| 05 Data Model | `FR-05-003`, `FR-05-005`, `FR-05-006`, `NFR-05-002`, `NFR-05-004` |
| 06 Backend API | `FR-06-003`, `FR-06-004`, `NFR-06-002`, `NFR-06-004` |
| 07 Frontend ChatBI | `FR-07-002`, `FR-07-005`, `NFR-07-001`, `NFR-07-002`, `NFR-07-004` |
| 08 RAG Retrieval and Evidence | `FR-08-003`, `FR-08-004`, `NFR-08-003`, `NFR-08-004` |
| 09 Analytics and Forecasting | `FR-09-006`, `NFR-09-002`, `NFR-09-003` |
| 10 Evaluation and Observability | `FR-10-002`, `FR-10-006`, `FR-10-008`, `NFR-10-001`, `NFR-10-002` |

## 5. Must-Fix Spec Smells

这些表述需要改写为可断言版本：

| Current wording | Problem | Required rewrite pattern |
|---|---|---|
| `SHOULD run in parallel` | SHOULD 不能作为强门禁 | 改成 MUST，或写明不实现也不失败的条件 |
| `known task type` | known 集合未定义 | 列出 task type enum |
| `any question` | 输入空间无限 | 改成 benchmark set 或 supported grammar |
| `stable for the same question input` | stable 未定义 | 相同输入连续 N 次输出完全相同 canonical IDs |
| `safe message` | safe 主观 | 禁止包含 raw SQL / PII / stack trace，并匹配 error_code |
| `full context` | full 未定义 | 列出 audit record required fields |
| `normal load` / `expected load` | 环境未定义 | 写明并发、样本量、数据规模、mock/real LLM |
| `plausible intervals` | plausible 主观 | lower <= forecast <= upper，coverage >= threshold on fixture |
| `controllable to avoid alert fatigue` | 不可测 | 例如 false positive rate <= 5% over labeled alert fixture |
| `correct values` | correct 未绑定 fixture | 提供 fixture 和 exact expected output |

## 6. Definition of Ready for Implementation

一个 spec 文件只有满足以下 checklist，才可以进入实现：

- 所有 `FR-*` / `NFR-*` 都在 Traceability Matrix 中出现。
- 所有 `AC-*` 都是 pass/fail 句子，而不是设计描述。
- 所有 `TC-*` 都有测试层级：unit / integration / e2e / negative / performance / compliance。
- 所有 contracts 都有 typed schema 或明确计划生成 typed schema。
- 所有 enum 都列出完整取值。
- 所有性能 NFR 都有数据集、并发、运行环境、统计窗口。
- 所有 LLM / agent 非确定性测试都使用 mock、golden fixture 或明确容忍区间。
- Open Questions 不影响当前实现；若影响，必须先决策。

## 7. Small-Step Implementation Rule

实现顺序必须以最小可回滚单元推进：

```text
one endpoint -> one failing test -> one implementation -> pyright -> pytest -> commit
one policy rule -> one failing test -> one implementation -> pyright -> pytest -> commit
one agent step -> one failing test -> one implementation -> pyright -> pytest -> commit
```

禁止一次性实现整个服务。每一步的爆炸半径必须控制在一个端点、一个规则、一个 agent step 或一个 schema 内。

推荐第一批红绿循环：

1. `POST /api/v1/chat/query` request/response schema only.
2. Missing auth returns `AUTH_UNAUTHORIZED`.
3. Valid question returns unified envelope with `trace_id`.
4. Guardrail rejects `DROP TABLE` with `SQL_DENY_STATEMENT`.
5. Query history writes one record for success and failure.
6. Replay by `trace_id` returns original input fields.

## 8. Spec Review Output Format

每次审一份 spec，输出必须包含：

```text
Decision: Pass / Conditional Pass / Fail
Blocking issues:
- Requirement ID: issue, required rewrite, verifier type
Non-blocking issues:
- Requirement ID: issue
Missing tests:
- Requirement ID -> required TC
Suggested first red-green step:
- Endpoint/rule/module:
- Failing test:
- Type gate:
- Rollback unit:
```

只有 `Pass` 或完成所有 blocking issue 的 `Conditional Pass`，才能进入代码实现。
