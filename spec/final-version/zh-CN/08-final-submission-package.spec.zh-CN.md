# Spec FV-08：最终提交包

来源设计：
- [最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)
- [Final Version 系统设计总目录](../../../system_design/final-version/zh-CN/README.zh-CN.md)

## 1. 目的
定义提交给总监评审所需的最终 artifacts、verification gates、demo script、文档和验收清单。

## 2. 范围
范围内：
- 中英文 README、final system design、final specs、API docs、local startup guide、cloud guide、verification reports、demo script、risk register、next steps。
- type checks、tests、security、evals、smoke tests、human demo acceptance 的 release readiness gate。

范围外：
- 法务合规认证。
- SOC 2 或 ISO 正式审计。

## 3. 功能需求
| ID | 需求 |
|---|---|
| FR-FV08-001 | 仓库必须包含英文和中文项目 README。 |
| FR-FV08-002 | 仓库必须包含英文和中文 final-version system design docs。 |
| FR-FV08-003 | 仓库必须包含英文和中文 final-version specs。 |
| FR-FV08-004 | API 文档必须描述 auth、chat、RAG、admin、eval、observability endpoints。 |
| FR-FV08-005 | 本地启动指南必须描述 required services、env vars、seed、tests、demo flow。 |
| FR-FV08-006 | 云端部署指南必须描述 image build、secrets、Kubernetes deployment、smoke tests、rollback。 |
| FR-FV08-007 | verification report 必须包含 pyright、pytest、eval gate、security checks、smoke tests。 |
| FR-FV08-008 | demo script 必须覆盖 user flow 和 admin flow。 |
| FR-FV08-009 | final risk register 必须记录已知缺口和下一步。 |

## 4. 非功能需求
| ID | 需求 |
|---|---|
| NFR-FV08-001 | 最终文档必须使用稳定 relative links。 |
| NFR-FV08-002 | 环境准备完成后，最终 demo 应能在 15 分钟内跑完。 |
| NFR-FV08-003 | baseline tests 不得依赖真实 LLM calls。 |
| NFR-FV08-004 | 所有最终 artifacts 必须能从 root README 找到。 |

## 5. 验收标准
| ID | 标准 |
|---|---|
| AC-FV08-001 | reviewer 从 root README 出发可以找到所有 final docs、specs、runbooks。 |
| AC-FV08-002 | machine gates 通过：type checks、tests、eval gate、security scan、smoke tests。 |
| AC-FV08-003 | demo script 证明 sign-in、chat query、RAG citation、admin observability、release gate。 |
| AC-FV08-004 | risks 和 not-yet-production items 明确写出，不能隐藏。 |
| AC-FV08-005 | 英文和中文 final-version docs 都存在。 |

## 6. 测试计划
| ID | 层级 | 描述 |
|---|---|---|
| TC-FV08-001 | docs | 对 README、final system design、final specs 做 link check。 |
| TC-FV08-002 | ci | 运行 README 中记录的 pyright 和 pytest 命令。 |
| TC-FV08-003 | eval | 用 passing 和 failing fixtures 跑 release gate。 |
| TC-FV08-004 | security | 运行 secret scan，确认没有明文 secret。 |
| TC-FV08-005 | smoke | 运行 local 或 staging smoke test。 |
| TC-FV08-006 | human acceptance | 按 demo script 执行并记录 pass/fail notes。 |
| TC-FV08-007 | docs parity | 验证中英文 final-version doc sets 包含匹配编号文件。 |

## 7. 追踪矩阵
| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV08-001 | AC-FV08-001 | TC-FV08-001 |
| FR-FV08-002 | AC-FV08-005 | TC-FV08-007 |
| FR-FV08-003 | AC-FV08-005 | TC-FV08-007 |
| FR-FV08-004 | AC-FV08-001 | TC-FV08-001 |
| FR-FV08-005 | AC-FV08-003 | TC-FV08-006 |
| FR-FV08-006 | AC-FV08-002 | TC-FV08-005 |
| FR-FV08-007 | AC-FV08-002 | TC-FV08-002, TC-FV08-003, TC-FV08-004 |
| FR-FV08-008 | AC-FV08-003 | TC-FV08-006 |
| FR-FV08-009 | AC-FV08-004 | TC-FV08-001 |

