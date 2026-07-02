# Spec FV-01：Auth、RBAC 与多租户隔离

来源设计：
- [Auth/RBAC 设计](../../../system_design/final-version/zh-CN/02-auth-rbac-tenant-isolation.zh-CN.md)
- [最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)

## 1. 目的
定义真实 LLM、RAG、Admin 可观测性和云端部署进入生产就绪前必须具备的用户、组织、角色、权限和租户隔离层。

## 2. 范围
范围内：
- 注册、登录、access token、refresh token、密码哈希、session 撤销。
- 组织成员、角色、权限、admin-only API enforcement。
- chat history、trace、document、embedding、eval、audit 的租户隔离。

范围外：
- 第一阶段不做企业 SSO/SAML/OIDC federation。
- 第一阶段不做超出表/字段/文档策略 hook 的细粒度业务行级权限。

## 3. 角色
| 角色 | 说明 |
|---|---|
| 匿名用户 | 只能注册或登录。 |
| 业务用户 | 可以执行被授权的 ChatBI 查询并查看自己的历史。 |
| 分析师 | 可以访问共享分析资产和已批准的 eval 任务。 |
| 管理员 | 可以管理用户、角色、策略、audit、trace、eval 和 release gate。 |

## 4. 功能需求
| ID | 需求 |
|---|---|
| FR-FV01-001 | 系统必须支持用户注册，email 唯一，密码必须安全哈希保存。 |
| FR-FV01-002 | 系统必须支持登录，并签发短期 access token。 |
| FR-FV01-003 | 系统必须支持 refresh-token rotation 或等价 session 更新机制。 |
| FR-FV01-004 | 每个已认证请求必须解析出 `user_id`、`org_id`、`roles` 和 `permissions`。 |
| FR-FV01-005 | Admin-only endpoints 必须对非管理员返回 403。 |
| FR-FV01-006 | 租户范围内的数据必须包含 `org_id` 或等价租户范围字段。 |
| FR-FV01-007 | Chat history、traces、evals、documents、embeddings 和 audits 必须按租户过滤。 |
| FR-FV01-008 | 角色和权限变更必须创建 audit events。 |
| FR-FV01-009 | v2 auth API 必须暴露 sign-up、sign-in、refresh 和 refresh-session revocation endpoints。 |
| FR-FV01-010 | HTTP handlers 必须从 access token 推导有效 `user_id`、`org_id`、roles 和 permissions，不能信任客户端传入身份字段；显式 development/test compatibility token 除外。 |
| FR-FV01-011 | 生产部署必须具备 organizations、users、refresh sessions 和 role audit events 的持久化 auth tables。 |
| FR-FV01-012 | 持久化 RAG document、chunk、embedding metadata、evidence、evaluation、analytics result 和 guardrail audit tables 必须包含 `org_id` 和租户查询索引。 |
| FR-FV01-013 | v2 eval run、eval report、latest release-gate 和 document-index endpoints 必须执行 admin 权限校验。 |
| FR-FV01-014 | Document-index async task payloads 和 idempotency cache keys 必须按 `org_id` 做租户隔离。 |
| FR-FV01-015 | Legacy v1 admin、observability、eval、release-gate 和 document-index endpoints 必须解析真实 signed-token `AuthContext` 并执行相同 admin 权限，同时保留显式本地 `test-token` compatibility path。 |
| FR-FV01-016 | 角色或权限变更必须让被变更用户已签发的 access tokens 失效；refresh flows 必须用当前 roles 和 permissions 签发新 tokens。 |
| FR-FV01-017 | Refresh-session HTTP flows 必须 rotate refresh tokens、拒绝重用或已撤销 refresh tokens，并让 session revoke 幂等且不泄露提交的 refresh token 是否存在。 |
| FR-FV01-018 | Access-token payload 必须最小化为认证和授权 claims，不得包含 password hashes、refresh tokens、email addresses 或明文凭据材料。 |
| FR-FV01-019 | Chat-history 和 query-detail endpoints 对真实 signed tokens 必须只返回认证用户自己的 records，并忽略客户端传入的 `user_id`；显式 development/test compatibility token 除外。 |
| FR-FV01-020 | Async task payloads、task-status lookups 和 analytics-result lookups 必须按认证 `org_id` 和 `user_id` 隔离；跨租户查找必须返回 not found 且不泄露资源细节。 |

## 5. 非功能需求
| ID | 需求 |
|---|---|
| NFR-FV01-001 | 密码绝不能明文存储或写入日志。 |
| NFR-FV01-002 | 使用 mocked storage 时，auth dependency 本地 P95 开销应 <= 50ms。 |
| NFR-FV01-003 | Token secrets 必须来自环境变量或 secret manager，不能硬编码。 |
| NFR-FV01-004 | 授权失败不能泄露其他租户资源是否存在。 |
| NFR-FV01-005 | Structured logs 可以为隐私遮蔽 user identifiers，但已认证 request metadata 和 trace context 必须保留可审计的 `user_id` 和 `org_id`。 |
| NFR-FV01-006 | Authentication 和 authorization error responses 不得回显提交的 passwords、access tokens、refresh tokens、bearer header values 或明文凭据材料。 |

## 6. 契约
### 6.1 SignUpRequest
必填字段：
- `email: str`
- `password: str`
- `display_name: str`
- `organization_name: str | null`

### 6.2 AuthContext
必填字段：
- `user_id: str`
- `org_id: str`
- `roles: list[str]`
- `permissions: list[str]`
- `trace_id: str`
- `token_version: int`

### 6.3 Token Contract
Access tokens：
- 必须用 `CHATBI_AUTH_TOKEN_SECRET`、注入配置或等价 runtime secret source 提供的 secret 签名。
- 必须包含 subject user id、organization id、roles、permissions、issued-at timestamp 和 expiration timestamp。
- 必须包含 user token version 或等价 revocation marker。
- 过期、格式错误、签名 secret 错误，或角色/权限变更后 stale 的 token 必须被拒绝。
- 不得包含 password hashes、refresh tokens、email addresses、API keys 或明文凭据。

Refresh tokens：
- 只能以 keyed hash 形式存储。
- refresh 时必须撤销旧 refresh session 并签发新的 refresh token。
- 必须支持显式撤销。

### 6.4 权限示例
| 资源 | 权限 |
|---|---|
| Chat query | `chat:query` |
| 自己的 history | `chat:history:read:self` |
| Trace read | `admin:trace:read` |
| Eval read | `admin:eval:read` |
| Eval run | `admin:eval:write` |
| Release gate read | `admin:release_gate:read` |
| User management | `admin:user:write` |
| Role audit read | `admin:audit:read` |
| Document indexing | `documents:index` |

### 6.5 Development/Test Compatibility
本地 HTTP tests 可以使用 `Authorization: Bearer test-token`。该 token 会解析为 admin `AuthContext`，仅用于本地 fixture 向后兼容。生产 auth flows 必须使用 auth service 签发的 signed access tokens。

### 6.6 持久化 Auth Tables
必需 PostgreSQL tables：
- `auth.organizations`
- `auth.users`
- `auth.refresh_sessions`
- `auth.role_audit_events`

Auth migration 必须创建 unique email lookup、organization lookup、active refresh-session lookup 和 tenant-scoped role audit listing 的索引。`auth.users.token_version` 必须存在，用于 role changes 后的 access-token invalidation。`auth.refresh_sessions.refresh_token_hash` 必须唯一，且只能存储 keyed refresh-token hashes。

### 6.7 租户范围持久化 Tables
必需 tenant-scoped PostgreSQL tables：
- `rag.documents`
- `rag.chunks`
- `rag.embedding_metadata`
- `rag.evidence_events`
- `evaluation.eval_cases`
- `evaluation.eval_runs`
- `evaluation.eval_scores`
- `analytics.results`
- `query_audit_events`

读取 documents、chunks、embedding metadata、evidence events、analytics results、query results、request metadata 或 audits 的 repository methods 必须支持按 `org_id` 过滤。跨租户 lookups 必须对调用方返回 no row。

## 7. 验收标准
| ID | 标准 |
|---|---|
| AC-FV01-001 | 新用户可以注册、登录，并调用一个需要认证的 chat endpoint。 |
| AC-FV01-002 | 普通用户访问 admin trace/eval/release-gate endpoints 时收到 403。 |
| AC-FV01-003 | Tenant A 不能读取 Tenant B 的 chat history、traces、documents、embeddings、evals 或 audits。 |
| AC-FV01-004 | 每个 chat query 都会写出包含 `user_id` 和 `org_id` 的 trace/log context。 |
| AC-FV01-005 | 角色变更会创建只有管理员可见的 audit events。 |
| AC-FV01-006 | Refresh token rotation 后重用旧 refresh token 必须被拒绝。 |
| AC-FV01-007 | 当 trace 只存在于其他租户时，query result 和 request metadata lookups 返回 404。 |
| AC-FV01-008 | 启用 PostgreSQL auth wiring 后，sign-up state、refresh sessions 和 role audit events 会通过 auth repository contract 持久化。 |
| AC-FV01-009 | RAG document/embedding/evidence 和 guardrail audit repository reads 可按 `org_id` 过滤，并且 migrations 为 eval、RAG 和 audit rows 创建 tenant indexes。 |
| AC-FV01-010 | Business user 访问 v2 eval、release-gate 和 document-index admin endpoints 时收到 403。 |
| AC-FV01-011 | 两个租户使用相同 document-index idempotency key 时，会获得各自 `org_id` 下的独立 tasks。 |
| AC-FV01-012 | 使用真实 signed token 的 business user 访问 v1 management surfaces 时收到 403；admin signed token 可以使用 v1 eval 和 document-index workflows，且不信任 spoofed `user_id` query parameters。 |
| AC-FV01-013 | Eval reports 和 latest release-gate summaries 按 `org_id` 隔离；租户 admin 不能读取另一个租户的 eval run 或 release-gate state。 |
| AC-FV01-014 | Admin 修改自身 `org_id` 之外用户角色时返回 404，不改变 roles，不写 role-audit rows，也不泄露目标用户租户 identifiers。 |
| AC-FV01-015 | 用户 roles 变更后，该用户此前签发的 access tokens 被拒绝；refresh/sign-in flows 产生带当前 roles 和 permissions 的 tokens。 |
| AC-FV01-016 | Failed sign-in、refresh、bearer-token authentication 和 invalid password sign-up responses 不回显提交的 passwords 或 token values。 |
| AC-FV01-017 | v2 refresh 会 rotate refresh token、拒绝旧 token 重用；显式 refresh-session revoke 会让之后 refresh 失败，同时 unknown tokens 返回同一 response shape。 |
| AC-FV01-018 | 签发的 access tokens 只包含文档化 auth claims（`typ`、`sub`、`org`、`roles`、`permissions`、`ver`、`iat`、`exp`），不包含凭据字段。 |
| AC-FV01-019 | 真实 signed token 请求 chat history 或 query detail 并传入另一个用户的 `user_id` 时，响应只包含 token 用户的数据，不包含其他用户的问题或 identifiers。 |
| AC-FV01-020 | 租户即使知道另一个租户的 async task id 或 analytics trace id，也不能读取对方 task status 或 analytics result；analytics/task payloads 包含 token-derived `org_id` 和 `user_id`；持久化 analytics result rows 暴露一等 `org_id` 和 `user_id` columns 以及 tenant lookup indexes。 |
| AC-FV01-021 | 使用 mocked storage 时，access-token authentication 本地 P95 latency <= 50ms。 |
| AC-FV01-022 | Token signing secrets 来自 `CHATBI_AUTH_TOKEN_SECRET`、注入配置或 per-process runtime secret；测试会拒绝固定 hard-coded fallback secrets。 |

## 8. 测试计划
| ID | 层级 | 描述 |
|---|---|---|
| TC-FV01-001 | unit | Password hashing verification 拒绝明文比较并接受正确密码。 |
| TC-FV01-002 | unit | Token validation 拒绝 expired、malformed 和 wrong-signature tokens。 |
| TC-FV01-003 | integration | Sign up、sign in，并调用 authenticated endpoint。 |
| TC-FV01-004 | integration negative | Business user 调用 admin endpoint 收到 403。 |
| TC-FV01-005 | integration negative | Tenant A 请求 Tenant B resource 时收到 404 或 403，且无 data leakage。 |
| TC-FV01-006 | integration | Chat query trace 包含 `user_id` 和 `org_id`。 |
| TC-FV01-007 | audit | Role change 写入包含 actor、target、action 和 timestamp 的 audit event。 |
| TC-FV01-008 | security | Observability log sanitization 会遮蔽 free-text messages 和 structured attributes 中的 plaintext passwords、bearer authorization headers、access tokens、refresh tokens、API keys 和 secrets。 |
| TC-FV01-009 | integration | Refresh rotation invalidates old refresh token 并签发 new pair。 |
| TC-FV01-010 | integration negative | Tenant A 读取 Tenant B request metadata 或 query result 时收到 404。 |
| TC-FV01-011 | integration | Admin role update endpoint 写入 tenant-scoped role audit event。 |
| TC-FV01-012 | unit/repository | PostgreSQL auth store 初始化 schema 并持久化 users，且不存 plaintext passwords。 |
| TC-FV01-013 | unit/repository | PostgreSQL auth store 加载/撤销 refresh sessions 并写入 tenant-scoped role audit rows。 |
| TC-FV01-014 | migration | Base migration 包含 `auth` schema 和 auth identity tables。 |
| TC-FV01-015 | unit/repository | PostgreSQL RAG repository 按 `org_id` 持久化和过滤 documents、chunks、embeddings 和 evidence。 |
| TC-FV01-016 | migration | RAG、evaluation 和 guardrail audit tables 包含 `org_id` 和 tenant lookup indexes。 |
| TC-FV01-017 | unit/repository | PostgreSQL guardrail audit store 持久化 `org_id` 并兼容 legacy audit rows。 |
| TC-FV01-018 | integration negative | Business user 访问 v2 eval run、release-gate read 和 document-index endpoints 时收到 403。 |
| TC-FV01-019 | integration | Admin 可以运行 v2 eval、读取 report，并读取 latest release-gate summary。 |
| TC-FV01-020 | integration | Document-index idempotency 按租户隔离，queued payloads 包含 `org_id`。 |
| TC-FV01-021 | integration negative | 使用真实 signed token 的 business user 访问 v1 eval、quality dashboard、audit 和 document-index endpoints 时收到 403。 |
| TC-FV01-022 | integration | 使用真实 signed token 的 admin 可以运行 v1 eval 和 document indexing，queued document tasks 包含 token-derived `org_id`。 |
| TC-FV01-023 | integration negative | Tenant admin 读取另一个租户 eval report 时收到 404，且看不到该租户 latest release-gate summary。 |
| TC-FV01-024 | unit/repository | Evaluation repository 用 `org_id` 存储 eval runs，并按租户过滤 run lookup/latest run。 |
| TC-FV01-025 | integration negative | Tenant admin 修改另一个租户用户 roles 时收到 404，响应不包含该用户 id 或 `org_id`。 |
| TC-FV01-026 | unit/repository | Auth stores 在写 user updates 或 role audit rows 前拒绝 cross-tenant role updates。 |
| TC-FV01-027 | unit/integration | Role changes 增加 user token version、拒绝 stale access tokens，并通过 refresh 产生带当前 roles 的 new access tokens。 |
| TC-FV01-028 | migration | Auth migrations 创建 `auth.users.token_version`，并包含 existing auth tables 的 additive column statement。 |
| TC-FV01-029 | integration negative | Wrong password、invalid refresh token、invalid bearer token 和 invalid sign-up password 的 auth error responses 不回显提交的 secret values。 |
| TC-FV01-030 | integration negative | v2 refresh 拒绝重用 rotated refresh token，且错误响应不回显旧 token。 |
| TC-FV01-031 | integration negative | v2 refresh-session revoke 幂等，不泄露 token 是否存在，不回显提交 token values，并导致之后用该 token refresh 失败。 |
| TC-FV01-032 | unit/security | Access-token payload 只包含文档化 authorization claims，并排除 password hashes、refresh tokens、emails、API keys 和明文凭据。 |
| TC-FV01-033 | unit/integration negative | Chat history 和 query detail 按 effective authenticated user 过滤；v2 endpoints 对真实 signed tokens 忽略 spoofed `user_id` parameters。 |
| TC-FV01-034 | integration negative | Tenant B 使用 Tenant A 的 async document-index task id 时收到 `TASK_NOT_FOUND`，响应不包含 Tenant A task details。 |
| TC-FV01-035 | integration | v2 analytics results 和 analytics/document-index async task payloads 包含 token-derived `org_id` 和 `user_id`。 |
| TC-FV01-036 | integration negative | Tenant B 使用 Tenant A analytics result trace id 时收到 `ANALYTICS_RESULT_NOT_FOUND`，响应不包含 Tenant A result details。 |
| TC-FV01-037 | migration/unit | Analytics result SQL、row mapping、repository 和 data-model catalog 包含一等 `org_id`、`user_id` fields、tenant lookup indexes，以及 pre-existing rows 的 legacy-row defaults。 |
| TC-FV01-038 | unit/performance | Mocked access-token authentication loop 报告 P95 latency <= 50ms。 |
| TC-FV01-039 | unit/security | Default auth service 接受 injected environment token secret；未配置 environment secret 时使用 distinct runtime secrets。 |

## 9. 追踪矩阵
| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV01-001 | AC-FV01-001 | TC-FV01-001, TC-FV01-003 |
| FR-FV01-002 | AC-FV01-001 | TC-FV01-002, TC-FV01-003 |
| FR-FV01-003 | AC-FV01-001 | TC-FV01-002 |
| FR-FV01-004 | AC-FV01-004 | TC-FV01-006 |
| FR-FV01-005 | AC-FV01-002 | TC-FV01-004 |
| FR-FV01-006 | AC-FV01-003 | TC-FV01-005 |
| FR-FV01-007 | AC-FV01-003, AC-FV01-013 | TC-FV01-005, TC-FV01-023, TC-FV01-024 |
| FR-FV01-008 | AC-FV01-005, AC-FV01-014 | TC-FV01-007, TC-FV01-011, TC-FV01-025, TC-FV01-026 |
| FR-FV01-009 | AC-FV01-001, AC-FV01-006 | TC-FV01-003, TC-FV01-009 |
| FR-FV01-010 | AC-FV01-003, AC-FV01-004 | TC-FV01-006, TC-FV01-010 |
| FR-FV01-011 | AC-FV01-008 | TC-FV01-012, TC-FV01-013, TC-FV01-014 |
| FR-FV01-012 | AC-FV01-003, AC-FV01-009, AC-FV01-020 | TC-FV01-015, TC-FV01-016, TC-FV01-017, TC-FV01-037 |
| FR-FV01-013 | AC-FV01-002, AC-FV01-010 | TC-FV01-018, TC-FV01-019 |
| FR-FV01-014 | AC-FV01-003, AC-FV01-011 | TC-FV01-020 |
| FR-FV01-015 | AC-FV01-012 | TC-FV01-021, TC-FV01-022 |
| FR-FV01-016 | AC-FV01-015 | TC-FV01-027, TC-FV01-028 |
| FR-FV01-017 | AC-FV01-017 | TC-FV01-030, TC-FV01-031 |
| FR-FV01-018 | AC-FV01-018 | TC-FV01-032 |
| FR-FV01-019 | AC-FV01-019 | TC-FV01-033 |
| FR-FV01-020 | AC-FV01-020 | TC-FV01-034, TC-FV01-035, TC-FV01-036, TC-FV01-037 |
| NFR-FV01-001 | AC-FV01-001, AC-FV01-016 | TC-FV01-001, TC-FV01-008, TC-FV01-012, TC-FV01-029 |
| NFR-FV01-002 | AC-FV01-021 | TC-FV01-038 |
| NFR-FV01-003 | AC-FV01-022 | TC-FV01-039 |
| NFR-FV01-004 | AC-FV01-003, AC-FV01-007, AC-FV01-014, AC-FV01-020 | TC-FV01-005, TC-FV01-010, TC-FV01-023, TC-FV01-025, TC-FV01-034, TC-FV01-036 |
| NFR-FV01-005 | AC-FV01-004 | TC-FV01-006 |
| NFR-FV01-006 | AC-FV01-016 | TC-FV01-029 |

## 10. 实现说明
- 已在 `src/chatbi/auth.py` 中实现 PBKDF2 password hashes 和 signed HMAC access tokens，没有引入第三方 auth dependency。
- `PostgresAuthStore` 在 `auth` schema 中持久化 organizations、users、refresh sessions 和 role audit events。`AUTH_TABLES_SQL` 已纳入 base migration。
- `create_app(..., auth_service=...)` 支持 tests 和 production wiring 注入 auth service。`create_app(..., auth_connect=..., use_postgres_metadata=True)` 显式接入 PostgreSQL auth store。若本地开发未配置 environment secret，会生成 per-process runtime secret，而不是 hard-coded secret。
- v2 chat requests 会在 request metadata 和 runtime query result records 中持久化 `org_id`。
- RAG v2 documents、chunks、embedding metadata、evidence events、evaluation tables 和 v2 guardrail audit events 在 PostgreSQL schema 中包含 `org_id`。RAG repository read methods 接受 optional `org_id` filters。
- v2 eval run/report 和 latest release-gate endpoints 执行 `admin:eval:write`、`admin:eval:read` 和 `admin:release_gate:read`。v2 document indexing 执行 `documents:index`。
- v2 document-index tasks 包含 `org_id`；idempotency cache keys 使用 `(endpoint, org_id, idempotency_key)` 防止跨租户 task reuse。
- v2 request metadata、runtime query result 和 governance trace lookups 使用 tenant checks，并对 cross-tenant access 返回 404，避免 resource-existence leakage。
- v1 document indexing、audit、observability traces、quality dashboard、eval run 和 eval report 等 management surfaces 现在会认证真实 signed tokens 并执行 admin permissions。对真实 tokens，effective user identity 来自 token，而不是 `user_id` query parameters。
- Evaluation runs 会持久化 `org_id`；eval report lookup 和 latest release-gate summaries 按认证租户解析。
- Role update flows 将 cross-tenant targets 当作 not found。Store-level implementations 在 role mutation 或 audit insertion 前校验 target user's `org_id`。
- Access tokens 携带 `token_version`；role updates 会递增 `auth.users.token_version`，使该用户此前签发的 access tokens 认证失败，而 refreshed 或 newly signed-in tokens 携带当前 roles。
- Observability logs 会在 records 存储或渲染前清理 credential-like message fragments 和 structured attributes（`password`、bearer authorization、access/refresh tokens、API keys、secrets）。
- Auth error responses 使用 generic envelopes，绝不回显提交的 password 或 token values。
- Refresh-session HTTP flows 会在使用时 rotate refresh tokens，拒绝 reused 或 revoked refresh tokens，并返回不泄露 token hash 是否存在的幂等 revoke responses。
- Access tokens 使用最小 signed payload，只包含文档化 auth claims；refresh tokens 和 password material 永不出现在 access-token payload 中。
- Chat history 和 query detail 按 effective authenticated user 过滤。对真实 signed tokens，v2 history/detail endpoints 忽略 client-supplied `user_id` 并使用 token subject。
- v2 analytics results 和 analytics/document-index tasks 携带 token-derived `org_id` 和 `user_id`；task-status 和 analytics-result lookups 在 ownership 不匹配时返回 not found。
- `analytics.results` 存储一等 `org_id` 和 `user_id` columns 以及 tenant lookup indexes；缺少这些 fields 的 legacy result rows 会映射为显式 `org_legacy` 和 `user_legacy` owners。
- Mocked access-token authentication 有 P95 <= 50ms 的 unit performance guard。
- Default auth service construction 接受 `CHATBI_AUTH_TOKEN_SECRET`；未配置 local runtime secret 时，每个 service 获得 distinct per-process runtime secret，而不是 fixed fallback。
- Legacy `Bearer test-token` 仍然作为本地 development/test admin token 保留，使 existing API fixtures 在 final-version auth endpoints 引入后继续工作。

## 11. 第一轮 Red-Green 步骤
1. 先写普通用户访问 admin trace endpoint 返回 403 的失败测试。
2. 新增 `AuthContext` 模型和 fake auth dependency。
3. 新增 role/permission check helper。
4. 先给一个 scoped resource 增加 tenant filter tests，再推广到所有 scoped resources。
