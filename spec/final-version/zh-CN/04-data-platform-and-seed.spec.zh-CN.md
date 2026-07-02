# Spec FV-04：数据平台与 Seed 数据

来源设计：
- [数据平台设计](../../../system_design/final-version/zh-CN/05-data-platform-and-seed.zh-CN.md)
- [最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)

## 1. 目的
定义 migration、可重复 seed 数据、数据质量检查和测试数据规模，用来验证最终平台。

## 2. 范围
范围内：
- application、business、knowledge、runtime 四类数据域。
- schema migration、seed profiles、data quality checks、CI/local commands。
- small、medium、large 三档数据。

范围外：
- 真实客户生产数据接入。
- 替代企业数仓。

## 3. 功能需求
| ID | 需求 |
|---|---|
| FR-FV04-001 | schema 变化必须通过 migration 表达。 |
| FR-FV04-002 | seed profile 必须包含 `small`、`medium`、`large`。 |
| FR-FV04-003 | small seed 必须支持 CI 和单元/集成测试。 |
| FR-FV04-004 | medium seed 必须支持本地端到端 demo 和集成测试。 |
| FR-FV04-005 | large seed 必须支持 load/performance testing。 |
| FR-FV04-006 | seed 数据必须至少包含两个租户，用于隔离测试。 |
| FR-FV04-007 | business records 和 documents 必须共享业务场景，支持带证据回答。 |
| FR-FV04-008 | seed command 必须可重复运行，支持幂等或安全 reset。 |

## 4. 非功能需求
| ID | 需求 |
|---|---|
| NFR-FV04-001 | small seed 本地应 <= 30s 完成。 |
| NFR-FV04-002 | CI 中 seed generation 不依赖真实 LLM 或 embedding API。 |
| NFR-FV04-003 | required table 或 vector 为空时，quality check 必须快速失败。 |
| NFR-FV04-004 | large seed 必须显式触发，不能默认在 CI 运行。 |

## 5. Seed Profile
| Profile | 用途 | 最小内容 |
|---|---|---|
| small | CI 和 smoke test | 2 个 org、5 个用户、几百业务行、document chunks |
| medium | 本地 demo | 5 个 org、几十用户、10 万业务行、几千 chunks |
| large | 压测 | 多 org、百万级业务行、大量 trace/query history |

## 6. 验收标准
| ID | 标准 |
|---|---|
| AC-FV04-001 | 一条命令可以重建本地 small demo 数据。 |
| AC-FV04-002 | CI 可以运行 small seed 和 quality checks。 |
| AC-FV04-003 | medium seed 支持一次带文档证据的端到端 ChatBI 查询。 |
| AC-FV04-004 | large seed 可以被显式生成用于 load testing。 |
| AC-FV04-005 | quality checks 验证外键、指标合理性、vector count、租户隔离。 |

## 7. 测试计划
| ID | 层级 | 描述 |
|---|---|---|
| TC-FV04-001 | migration | 从空数据库应用 migrations。 |
| TC-FV04-002 | seed | reset/idempotent 模式下连续运行 small seed 两次。 |
| TC-FV04-003 | quality | 验证 required tables、tenant counts、foreign keys。 |
| TC-FV04-004 | quality | 验证 chunk count 等于 vector count。 |
| TC-FV04-005 | integration | 运行一个 seeded business question 并检索匹配文档证据。 |
| TC-FV04-006 | negative | 故意混租户数据时 tenant leakage quality check 失败。 |
| TC-FV04-007 | load-prep | large seed command 必须显式触发，默认 CI 不跑。 |

## 8. 追踪矩阵
| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV04-001 | AC-FV04-001 | TC-FV04-001 |
| FR-FV04-002 | AC-FV04-004 | TC-FV04-002, TC-FV04-007 |
| FR-FV04-003 | AC-FV04-002 | TC-FV04-002 |
| FR-FV04-004 | AC-FV04-003 | TC-FV04-005 |
| FR-FV04-005 | AC-FV04-004 | TC-FV04-007 |
| FR-FV04-006 | AC-FV04-005 | TC-FV04-003, TC-FV04-006 |
| FR-FV04-007 | AC-FV04-003 | TC-FV04-005 |
| FR-FV04-008 | AC-FV04-001 | TC-FV04-002 |

