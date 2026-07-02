# Spec FV-05：Admin 可观测性

来源设计：
- [安全与 Admin 可观测性设计](../../../system_design/final-version/zh-CN/08-security-observability-admin.zh-CN.md)
- [最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)

## 1. 目的
定义 Spec 10 中 trace、metrics、eval、release gate、audit 等能力的管理员专属访问边界。

## 2. 范围
范围内：
- trace、metrics、eval report、release gate、audit event、security event 的 admin authorization。
- log、trace、audit record 中的 user/org context。
- 敏感信息脱敏和 Admin Dashboard API。

范围外：
- 自研完整 APM 产品。
- 替代云厂商或开源可观测平台。

## 3. 功能需求
| ID | 需求 |
|---|---|
| FR-FV05-001 | Trace、eval、audit、release-gate API 必须需要 admin 权限。 |
| FR-FV05-002 | request-scoped observability record 必须包含 `trace_id`、`user_id`、`org_id`。 |
| FR-FV05-003 | 管理员访问敏感 observability 数据本身也必须被审计。 |
| FR-FV05-004 | 日志必须 mask password、token、secret 和配置的 PII 字段。 |
| FR-FV05-005 | Admin dashboard API 必须暴露 system health、LLM health、SQL safety、RAG health、eval、release gate、audit。 |
| FR-FV05-006 | release gate failure 必须对管理员可见，并阻止最终 release workflow。 |
| FR-FV05-007 | 普通用户绝不能看到 global traces、evals、release gates、audit events。 |

## 4. 非功能需求
| ID | 需求 |
|---|---|
| NFR-FV05-001 | 10k mock events 下 admin dashboard summary endpoint 本地 P95 应 <= 500ms。 |
| NFR-FV05-002 | request-scoped logs 必须是 structured JSON。 |
| NFR-FV05-003 | audit records 从应用视角必须 append-only。 |
| NFR-FV05-004 | observability query 必须按租户过滤，除非 caller 有 global admin 权限。 |

## 5. 契约
### 5.1 AdminDashboardSummary
- `system_health: dict`
- `llm_health: dict`
- `sql_safety: dict`
- `rag_health: dict`
- `eval_summary: dict`
- `release_gate: dict`
- `audit_summary: dict`

### 5.2 AuditEvent
- `event_id: str`
- `actor_user_id: str`
- `org_id: str`
- `action: str`
- `target_type: str`
- `target_id: str`
- `timestamp: datetime`
- `metadata: dict`

## 6. 验收标准
| ID | 标准 |
|---|---|
| AC-FV05-001 | 管理员可以查看 trace、eval report、release gate status、audit summary。 |
| AC-FV05-002 | 普通用户访问所有 admin observability endpoints 都返回 403。 |
| AC-FV05-003 | 管理员读取敏感 observability endpoint 会生成 audit event。 |
| AC-FV05-004 | logs 和 traces 包含 user/org context，但不泄露 secret。 |
| AC-FV05-005 | release gate 失败会阻止 release workflow。 |

## 7. 测试计划
| ID | 层级 | 描述 |
|---|---|---|
| TC-FV05-001 | integration | 管理员成功读取 dashboard summary。 |
| TC-FV05-002 | integration negative | 普通用户读取 trace/eval/release gate 返回 403。 |
| TC-FV05-003 | audit | 管理员读取 trace 写入 audit event。 |
| TC-FV05-004 | security | log masking 移除 token/password/secret。 |
| TC-FV05-005 | release | failed release gate 停止 release command 或 CI job。 |
| TC-FV05-006 | tenant | 租户管理员不能读取其他租户 observability 数据。 |
| TC-FV05-007 | benchmark | 10k mock events 下 dashboard summary P95。 |

## 8. 追踪矩阵
| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV05-001 | AC-FV05-002 | TC-FV05-002 |
| FR-FV05-002 | AC-FV05-004 | TC-FV05-004 |
| FR-FV05-003 | AC-FV05-003 | TC-FV05-003 |
| FR-FV05-004 | AC-FV05-004 | TC-FV05-004 |
| FR-FV05-005 | AC-FV05-001 | TC-FV05-001 |
| FR-FV05-006 | AC-FV05-005 | TC-FV05-005 |
| FR-FV05-007 | AC-FV05-002 | TC-FV05-002 |

