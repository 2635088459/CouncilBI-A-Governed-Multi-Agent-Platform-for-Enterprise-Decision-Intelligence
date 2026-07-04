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
| FR-FV04-009 | Seed generation 必须生成 deterministic business rows 和 vector RAG documents，并共享同一组 demo scenarios。 |
| FR-FV04-010 | 本地 seed command 必须能运行 small seed 和 quality checks，且不依赖真实 provider API。 |
| FR-FV04-011 | Seed command 必须能导出 deterministic local JSON artifact，供审查和后续导入使用。 |
| FR-FV04-012 | 已导出的 seed artifact 必须能在不重新生成 seed dataset 的情况下独立读取和质量校验。 |
| FR-FV04-013 | 本地 Docker demo seed 必须包含 deterministic 的 2012 月度 revenue 切片，使最高月份这类 aggregation question 由数据回答，而不是由 UI 硬编码。 |
| FR-FV04-014 | 当 SQL-backed demo answer 使用 seeded business rows 且没有走 document RAG route 时，应该返回 data-provenance evidence。 |
| FR-FV04-015 | 本地 Docker demo seed 必须包含至少一个非 revenue 的企业 read model，用于 support-ticket operations。 |
| FR-FV04-016 | Seeded business rows 和 knowledge documents 必须包含同一个 support-ticket 场景，使 answer synthesis 能结合表格数据和文档证据。 |

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
| AC-FV04-006 | Seeded vector RAG evidence 可以回答 seeded campaign/revenue scenario。 |
| AC-FV04-007 | 连续两次导出 small seed artifact 会产生 byte-identical JSON 内容。 |
| AC-FV04-008 | 已导出的 seed artifact 可以从磁盘重新读取并运行 quality checks，且损坏的 count 或租户关联会校验失败。 |
| AC-FV04-009 | 本地 Docker 查询 `Which month had the highest revenue in 2012?` 会返回 2012 数据、识别最高月份，并包含 data-provenance evidence。 |
| AC-FV04-010 | 本地 Docker 查询 support tickets 时会返回 support-ticket rows，包含 support-operations evidence，且不会使用 revenue read model。 |

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
| TC-FV04-008 | command | `chatbi-seed-final --profile small` 构建 small seed 并通过 quality checks。 |
| TC-FV04-009 | unit | Final seed profiles 暴露 deterministic small、medium 和 explicit-only large profiles。 |
| TC-FV04-010 | command | `chatbi-seed-final --profile small --output-json <path>` 写入 deterministic artifact JSON。 |
| TC-FV04-011 | command | `chatbi-seed-final --validate-json <path>` 重新读取已导出的 artifact 并运行 quality checks。 |
| TC-FV04-012 | integration | 2012 highest-revenue 查询返回 `2012-12`、12 个月度 rows 和 provenance evidence item。 |
| TC-FV04-012 | negative | artifact validation 在 JSON 内部 vector count mismatch 或 tenant leakage 时失败。 |
| TC-FV04-013 | migration | Base migration 创建并 seed `business.support_ticket_summary`。 |
| TC-FV04-014 | integration | Support-ticket question 返回非 revenue rows 和 document/data evidence。 |

已实现测试覆盖：
- `tests/test_final_seed.py`

已实现源码模块：
- `src/chatbi/final_seed.py`

已实现本地命令：
- `chatbi-seed-final --profile small`
- `chatbi-seed-final --profile small --output-json /tmp/chatbi-small-seed.json`
- `chatbi-seed-final --validate-json /tmp/chatbi-small-seed.json`

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
| FR-FV04-009 | AC-FV04-003, AC-FV04-006 | TC-FV04-005 |
| FR-FV04-010 | AC-FV04-001, AC-FV04-002 | TC-FV04-008 |
| FR-FV04-011 | AC-FV04-007 | TC-FV04-010 |
| FR-FV04-012 | AC-FV04-008 | TC-FV04-011, TC-FV04-012 |
| FR-FV04-013 | AC-FV04-009 | TC-FV04-012 |
| FR-FV04-014 | AC-FV04-009 | TC-FV04-012 |
| FR-FV04-015 | AC-FV04-010 | TC-FV04-013, TC-FV04-014 |
| FR-FV04-016 | AC-FV04-010 | TC-FV04-014 |
| NFR-FV04-002 | AC-FV04-002 | TC-FV04-002, TC-FV04-008 |
| NFR-FV04-004 | AC-FV04-004 | TC-FV04-007 |
