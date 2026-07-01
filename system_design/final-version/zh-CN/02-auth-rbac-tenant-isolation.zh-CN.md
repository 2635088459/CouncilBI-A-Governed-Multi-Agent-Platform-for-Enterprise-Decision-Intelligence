# 02 登录、注册、RBAC 与租户隔离

## 1. 为什么这一步优先级最高

如果没有用户体系，系统就只能是本地 Demo。只要准备上线或给别人试用，就必须回答：

1. 谁在用系统？
2. 他属于哪个组织？
3. 他能看哪些数据？
4. 他能不能看评估、trace、审计这些敏感信息？

所以 Auth/RBAC 是工业级项目的第一道门。

## 2. 用户模型

建议最少包含这些实体：

1. `users`：用户账号。
2. `organizations`：组织或租户。
3. `memberships`：用户和组织的关系。
4. `roles`：角色，例如 `user`、`analyst`、`admin`。
5. `permissions`：具体权限，例如 `chat:query`、`admin:trace:read`。
6. `sessions` 或 `refresh_tokens`：登录态。

## 3. 角色设计

### 3.1 普通用户

能做：

1. 登录系统。
2. 提问。
3. 查看自己的历史查询。
4. 查看自己有权限的数据结果。

不能做：

1. 查看其他用户的问题。
2. 查看全局 trace。
3. 查看 release gate。
4. 修改语义层或安全策略。

### 3.2 分析师

比普通用户多：

1. 查看团队共享查询。
2. 管理部分 semantic metrics。
3. 运行部分评估集。
4. 导出被授权的数据结果。

### 3.3 管理员

能做：

1. 管理用户和角色。
2. 查看审计日志。
3. 查看 trace、metrics、eval、release gate。
4. 管理模型配置和安全策略。
5. 查看系统健康状态。

管理员不是“超级用户随便查业务数据”。管理员看系统运行状态，但访问业务数据仍应受租户和数据权限限制。

## 4. 权限校验位置

权限不能只在前端做，后端必须做。

推荐每个请求进入 API 后都经过：

1. Authentication：你是谁。
2. Organization Resolution：你当前在哪个组织工作。
3. Authorization：你能不能做这个动作。
4. Data Scope：你能看到哪些表、字段、文档、trace。

## 5. Token 设计

可以使用：

1. Access Token：短期有效，调用 API 使用。
2. Refresh Token：长期一点，用于换取新的 access token。
3. Password Hash：使用安全哈希算法保存密码，不能明文存储。

Access token 中可包含：

1. `sub`：用户 ID。
2. `org_id`：当前组织。
3. `roles`：角色。
4. `permissions`：权限快照。
5. `exp`：过期时间。

## 6. 租户隔离

所有关键表都要有 `org_id` 或等价租户字段。

需要隔离的对象包括：

1. 用户查询历史。
2. 业务数据连接。
3. 文档和 embedding。
4. 评估结果。
5. 审计日志。
6. trace 和运行日志。

RAG 检索时尤其容易出问题：如果 vector search 没带 `org_id` filter，就可能把 A 公司的文档证据返回给 B 公司。

## 7. Admin-only 资源

以下接口必须要求管理员权限：

1. `GET /observability/traces`
2. `GET /observability/metrics`
3. `GET /evals/{id}`
4. `GET /release-gate`
5. `GET /audit/events`
6. `POST /admin/users`
7. `POST /admin/policies`

一句话：只要能看到别人行为、系统内部状态、质量评估、安全策略，就不能给普通用户开放。

## 8. 实施顺序

1. 新增用户、组织、角色、权限数据模型。
2. 新增注册和登录 API。
3. 给现有 API 加认证依赖。
4. 给 observability/eval/release gate 加 admin 权限。
5. 给 query history、RAG、trace 加 `org_id` 隔离。
6. 编写权限测试：普通用户访问 admin 接口必须 403。
