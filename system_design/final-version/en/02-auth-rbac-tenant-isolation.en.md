# 02 Auth, RBAC, and Tenant Isolation

## 1. Why This Comes First

Without a user system, the project remains a local demo. Once other people use it, the platform must know who the user is, which organization they belong to, what they can access, and whether they are allowed to view sensitive admin information.

Auth and RBAC are the first production boundary.

## 2. Data Model

Minimum entities:

1. `users`
2. `organizations`
3. `memberships`
4. `roles`
5. `permissions`
6. `sessions` or `refresh_tokens`

## 3. Roles

### Normal User

Can ask questions, view their own history, and access authorized data. Cannot view global traces, release gates, or other users' queries.

### Analyst

Can view shared team queries, manage selected semantic definitions, run approved evaluation sets, and export authorized data.

### Admin

Can manage users, roles, audit logs, traces, evaluation results, release gates, model configuration, and security policies.

Admin does not automatically mean unlimited business-data access. Business data must still respect tenant and data policies.

## 4. Authorization Flow

Every backend request should pass through:

1. Authentication: who are you?
2. Organization resolution: which tenant are you working in?
3. Authorization: can you perform this action?
4. Data scope: which tables, fields, documents, and traces can you see?

## 5. Token Design

Use short-lived access tokens and refresh tokens. Access tokens can include:

1. `sub`
2. `org_id`
3. `roles`
4. `permissions`
5. `exp`

Passwords must be hashed securely and never stored as plaintext.

## 6. Tenant Isolation

All sensitive records should carry `org_id` or an equivalent tenant scope:

1. Query history.
2. Business data connections.
3. Documents and embeddings.
4. Evaluation results.
5. Audit logs.
6. Traces and runtime logs.

RAG search must include tenant and permission filters, otherwise one organization's documents could leak into another organization's answer.

## 7. Admin-Only Resources

These endpoints should require admin permissions:

1. `GET /observability/traces`
2. `GET /observability/metrics`
3. `GET /evals/{id}`
4. `GET /release-gate`
5. `GET /audit/events`
6. `POST /admin/users`
7. `POST /admin/policies`

## 8. Implementation Order

1. Add users, organizations, roles, and permissions.
2. Add sign-up and sign-in APIs.
3. Add auth dependencies to existing APIs.
4. Make observability, eval, and release-gate APIs admin-only.
5. Add `org_id` scoping to history, RAG, and traces.
6. Add permission tests for 401 and 403 behavior.
