# Spec FV-01: Auth, RBAC, and Tenant Isolation

Source design:
- [Auth/RBAC design](../../../system_design/final-version/en/02-auth-rbac-tenant-isolation.en.md)
- [Final roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)

## 1. Purpose
Define the user, organization, role, permission, and tenant-isolation layer required before real LLM, RAG, admin observability, and cloud deployment can be considered production-ready.

## 2. Scope
In scope:
- Sign-up, sign-in, access tokens, refresh tokens, password hashing, session revocation.
- Organization membership, roles, permissions, and admin-only API enforcement.
- Tenant scoping for chat history, traces, documents, embeddings, evaluations, and audits.

Out of scope:
- SSO/SAML/OIDC enterprise federation in the first final-version milestone.
- Fine-grained row-level business entitlement beyond table/field/document policy hooks.

## 3. Actors
| Actor | Description |
|---|---|
| Anonymous user | Can sign up or sign in only. |
| Business user | Can run authorized ChatBI queries and see own history. |
| Analyst | Can access shared analysis assets and approved eval tasks. |
| Admin | Can manage users, roles, policies, audit, traces, evals, and release gates. |

## 4. Functional Requirements
| ID | Requirement |
|---|---|
| FR-FV01-001 | The system MUST support user sign-up with unique email and secure password hash. |
| FR-FV01-002 | The system MUST support sign-in and issue short-lived access tokens. |
| FR-FV01-003 | The system MUST support refresh-token rotation or equivalent session renewal. |
| FR-FV01-004 | Every authenticated request MUST resolve `user_id`, `org_id`, `roles`, and `permissions`. |
| FR-FV01-005 | Admin-only endpoints MUST reject non-admin users with 403. |
| FR-FV01-006 | Tenant-scoped records MUST include `org_id` or an equivalent tenant scope. |
| FR-FV01-007 | Chat history, traces, evals, documents, embeddings, and audits MUST be filtered by tenant. |
| FR-FV01-008 | Role and permission changes MUST create audit events. |
| FR-FV01-009 | The v2 auth API MUST expose sign-up, sign-in, refresh, and refresh-session revocation endpoints. |
| FR-FV01-010 | HTTP handlers MUST derive effective `user_id`, `org_id`, roles, and permissions from the access token, not from client-supplied identity fields, except for the explicit development/test compatibility token. |
| FR-FV01-011 | Production deployments MUST have persistent auth tables for organizations, users, refresh sessions, and role audit events. |
| FR-FV01-012 | Persistent RAG document, chunk, embedding metadata, evidence, evaluation, analytics result, and guardrail audit tables MUST include `org_id` and tenant lookup indexes. |
| FR-FV01-013 | v2 eval run, eval report, latest release-gate, and document-index endpoints MUST enforce admin permissions. |
| FR-FV01-014 | Document-index async task payloads and idempotency cache keys MUST be tenant-scoped by `org_id`. |
| FR-FV01-015 | Legacy v1 admin, observability, eval, release-gate, and document-index endpoints MUST resolve real signed-token `AuthContext` and enforce the same admin permissions, while preserving the explicit local `test-token` compatibility path. |
| FR-FV01-016 | Role or permission changes MUST invalidate previously issued access tokens for the changed user, while refresh flows issue tokens with the current roles and permissions. |
| FR-FV01-017 | Refresh-session HTTP flows MUST rotate refresh tokens, reject reused or revoked refresh tokens, and make session revocation idempotent without revealing whether a submitted refresh token existed. |
| FR-FV01-018 | Access-token payloads MUST be minimized to authentication and authorization claims and MUST NOT contain password hashes, refresh tokens, email addresses, or plaintext credential material. |
| FR-FV01-019 | Chat-history and query-detail endpoints MUST return only the authenticated user's records for real signed tokens and MUST ignore client-supplied `user_id` values except for the explicit development/test compatibility token. |
| FR-FV01-020 | Async task payloads, task-status lookups, and analytics-result lookups MUST be scoped to the authenticated `org_id` and `user_id`; cross-tenant lookups MUST return not found without resource details. |

## 5. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-FV01-001 | Passwords MUST never be stored or logged in plaintext. |
| NFR-FV01-002 | Auth dependency overhead SHOULD be P95 <= 50ms locally with mocked storage. |
| NFR-FV01-003 | Token secrets MUST come from environment or secret manager, never hard-coded. |
| NFR-FV01-004 | Authorization failures MUST not reveal whether another tenant's resource exists. |
| NFR-FV01-005 | Structured logs MAY mask user identifiers for privacy, but authenticated request metadata and trace context MUST preserve auditable `user_id` and `org_id`. |
| NFR-FV01-006 | Authentication and authorization error responses MUST NOT echo submitted passwords, access tokens, refresh tokens, bearer header values, or plaintext credential material. |

## 6. Contracts
### 6.1 SignUpRequest
Required fields:
- `email: str`
- `password: str`
- `display_name: str`
- `organization_name: str | null`

### 6.2 AuthContext
Required fields:
- `user_id: str`
- `org_id: str`
- `roles: list[str]`
- `permissions: list[str]`
- `trace_id: str`
- `token_version: int`

### 6.3 Token Contract
Access tokens:
- MUST be signed with a secret provided by `CHATBI_AUTH_TOKEN_SECRET`, injected configuration, or an equivalent runtime secret source.
- MUST include subject user id, organization id, roles, permissions, issued-at timestamp, and expiration timestamp.
- MUST include a user token version or equivalent revocation marker.
- MUST be rejected when expired, malformed, signed with the wrong secret, or stale after a role/permission change.
- MUST NOT include password hashes, refresh tokens, email addresses, API keys, or plaintext credentials.

Refresh tokens:
- MUST be stored only as a keyed hash.
- MUST rotate on refresh by revoking the previous refresh session and issuing a new refresh token.
- MUST support explicit revocation.

### 6.4 Required Permission Examples
| Resource | Permission |
|---|---|
| Chat query | `chat:query` |
| Own history | `chat:history:read:self` |
| Trace read | `admin:trace:read` |
| Eval read | `admin:eval:read` |
| Eval run | `admin:eval:write` |
| Release gate read | `admin:release_gate:read` |
| User management | `admin:user:write` |
| Role audit read | `admin:audit:read` |
| Document indexing | `documents:index` |

### 6.5 Development/Test Compatibility
The local HTTP tests may use `Authorization: Bearer test-token`. This token resolves to an admin `AuthContext` for backwards-compatible local fixtures only. Production auth flows MUST use signed access tokens issued by the auth service.

### 6.6 Persistent Auth Tables
Required PostgreSQL tables:
- `auth.organizations`
- `auth.users`
- `auth.refresh_sessions`
- `auth.role_audit_events`

The auth migration MUST create indexes for unique email lookup, organization lookup, active refresh-session lookup, and tenant-scoped role audit listing. `auth.users.token_version` MUST be present for access-token invalidation after role changes. `auth.refresh_sessions.refresh_token_hash` MUST be unique and MUST store only keyed refresh-token hashes.

### 6.7 Tenant-Scoped Persistence Tables
Required tenant-scoped PostgreSQL tables:
- `rag.documents`
- `rag.chunks`
- `rag.embedding_metadata`
- `rag.evidence_events`
- `evaluation.eval_cases`
- `evaluation.eval_runs`
- `evaluation.eval_scores`
- `analytics.results`
- `query_audit_events`

Repository methods that read documents, chunks, embedding metadata, evidence events, analytics results, query results, request metadata, or audits MUST support tenant filtering by `org_id`. Cross-tenant lookups MUST return no row to the caller.

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV01-001 | A new user can sign up, sign in, and call an authenticated chat endpoint. |
| AC-FV01-002 | A normal user receives 403 from admin trace/eval/release-gate endpoints. |
| AC-FV01-003 | Tenant A cannot read Tenant B chat history, traces, documents, embeddings, evals, or audits. |
| AC-FV01-004 | Every chat query emits trace/log context containing `user_id` and `org_id`. |
| AC-FV01-005 | Role changes create audit events visible only to admins. |
| AC-FV01-006 | Refresh token reuse after rotation is rejected. |
| AC-FV01-007 | Query result and request metadata lookups return 404 when the trace exists only in another tenant. |
| AC-FV01-008 | With PostgreSQL auth wiring enabled, sign-up state, refresh sessions, and role audit events are persisted through the auth repository contract. |
| AC-FV01-009 | RAG document/embedding/evidence and guardrail audit repository reads can be filtered by `org_id`, and migrations create tenant indexes for eval, RAG, and audit rows. |
| AC-FV01-010 | A business user receives 403 from v2 eval, release-gate, and document-index admin endpoints. |
| AC-FV01-011 | Two tenants using the same document-index idempotency key receive separate tasks scoped to their own `org_id`. |
| AC-FV01-012 | A business user with a real signed token receives 403 from v1 management surfaces, while an admin signed token can use v1 eval and document-index workflows without trusting spoofed `user_id` query parameters. |
| AC-FV01-013 | Eval reports and latest release-gate summaries are isolated by `org_id`; tenant admins cannot read another tenant's eval run or release-gate state. |
| AC-FV01-014 | Admin role updates for a user outside the admin's `org_id` return 404, do not change roles, do not write role-audit rows, and do not reveal the target user's tenant identifiers. |
| AC-FV01-015 | After a user's roles are changed, that user's previously issued access tokens are rejected and refresh/sign-in flows produce tokens with the current roles and permissions. |
| AC-FV01-016 | Failed sign-in, refresh, bearer-token authentication, and invalid password sign-up responses do not echo submitted passwords or token values. |
| AC-FV01-017 | v2 refresh rotates the refresh token, rejects reuse of the old token, and explicit refresh-session revoke causes later refresh to fail while returning the same response shape for unknown tokens. |
| AC-FV01-018 | Issued access tokens contain only the documented auth claims (`typ`, `sub`, `org`, `roles`, `permissions`, `ver`, `iat`, `exp`) and no credential fields. |
| AC-FV01-019 | When a real signed token requests chat history or query detail with another user's `user_id`, the response contains only the token user's data and no other user's questions or identifiers. |
| AC-FV01-020 | A tenant cannot read another tenant's async task status or analytics result even with a valid id, and analytics/task payloads include token-derived `org_id` and `user_id`; persisted analytics result rows expose first-class `org_id` and `user_id` columns plus tenant lookup indexes. |
| AC-FV01-021 | Access-token authentication with mocked storage has local P95 latency <= 50ms. |
| AC-FV01-022 | Token signing secrets come from `CHATBI_AUTH_TOKEN_SECRET`, injected configuration, or a per-process runtime secret; fixed hard-coded fallback secrets are rejected by tests. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-FV01-001 | unit | Password hashing verification rejects plaintext comparison and accepts valid password. |
| TC-FV01-002 | unit | Token validation rejects expired, malformed, and wrong-signature tokens. |
| TC-FV01-003 | integration | Sign up, sign in, call authenticated endpoint. |
| TC-FV01-004 | integration negative | Business user calls admin endpoint and receives 403. |
| TC-FV01-005 | integration negative | Tenant A requests Tenant B resource and receives 404 or 403 without data leakage. |
| TC-FV01-006 | integration | Chat query trace includes `user_id` and `org_id`. |
| TC-FV01-007 | audit | Role change writes an audit event with actor, target, action, and timestamp. |
| TC-FV01-008 | security | Observability log sanitization masks plaintext passwords, bearer authorization headers, access tokens, refresh tokens, API keys, and secrets in free-text messages and structured attributes. |
| TC-FV01-009 | integration | Refresh rotation invalidates the old refresh token and issues a new pair. |
| TC-FV01-010 | integration negative | Tenant A receives 404 when reading Tenant B request metadata or query result. |
| TC-FV01-011 | integration | Admin role update endpoint writes a tenant-scoped role audit event. |
| TC-FV01-012 | unit/repository | PostgreSQL auth store initializes schema and persists users without plaintext passwords. |
| TC-FV01-013 | unit/repository | PostgreSQL auth store loads/revokes refresh sessions and writes tenant-scoped role audit rows. |
| TC-FV01-014 | migration | Base migration includes `auth` schema and auth identity tables. |
| TC-FV01-015 | unit/repository | PostgreSQL RAG repository persists and filters documents, chunks, embeddings, and evidence by `org_id`. |
| TC-FV01-016 | migration | RAG, evaluation, and guardrail audit tables include `org_id` and tenant lookup indexes. |
| TC-FV01-017 | unit/repository | PostgreSQL guardrail audit store persists `org_id` and remains backward-compatible with legacy audit rows. |
| TC-FV01-018 | integration negative | Business user receives 403 from v2 eval run, release-gate read, and document-index endpoints. |
| TC-FV01-019 | integration | Admin can run a v2 eval, read its report, and read the latest release-gate summary. |
| TC-FV01-020 | integration | Document-index idempotency is isolated per tenant and queued payloads include `org_id`. |
| TC-FV01-021 | integration negative | Business user with a real signed token receives 403 from v1 eval, quality dashboard, audit, and document-index endpoints. |
| TC-FV01-022 | integration | Admin with a real signed token can run v1 eval and document indexing, and queued document tasks include the token-derived `org_id`. |
| TC-FV01-023 | integration negative | Tenant admin receives 404 for another tenant's eval report and does not see that tenant's latest release-gate summary. |
| TC-FV01-024 | unit/repository | Evaluation repository stores eval runs with `org_id` and filters run lookup/latest run by tenant. |
| TC-FV01-025 | integration negative | Tenant admin receives 404 when updating another tenant's user roles, and the response does not include that user's id or `org_id`. |
| TC-FV01-026 | unit/repository | Auth stores reject cross-tenant role updates before writing user updates or role audit rows. |
| TC-FV01-027 | unit/integration | Role changes increment user token version, reject stale access tokens, and refresh new access tokens with current roles. |
| TC-FV01-028 | migration | Auth migrations create `auth.users.token_version` and include an additive column statement for existing auth tables. |
| TC-FV01-029 | integration negative | Auth error responses for wrong password, invalid refresh token, invalid bearer token, and invalid sign-up password omit submitted secret values. |
| TC-FV01-030 | integration negative | v2 refresh rejects reuse of a rotated refresh token and does not echo the old token in the error response. |
| TC-FV01-031 | integration negative | v2 refresh-session revoke is idempotent, does not reveal token existence, does not echo submitted token values, and causes subsequent refresh with that token to fail. |
| TC-FV01-032 | unit/security | Access-token payload contains only documented authorization claims and excludes password hashes, refresh tokens, emails, API keys, and plaintext credentials. |
| TC-FV01-033 | unit/integration negative | Chat history and query detail are filtered by the effective authenticated user, and v2 endpoints ignore spoofed `user_id` parameters for real signed tokens. |
| TC-FV01-034 | integration negative | Tenant B receives `TASK_NOT_FOUND` for Tenant A's async document-index task id and the response omits Tenant A task details. |
| TC-FV01-035 | integration | v2 analytics results and analytics/document-index async task payloads include token-derived `org_id` and `user_id`. |
| TC-FV01-036 | integration negative | Tenant B receives `ANALYTICS_RESULT_NOT_FOUND` for Tenant A's analytics result trace id and the response omits Tenant A result details. |
| TC-FV01-037 | migration/unit | Analytics result SQL, row mapping, repository, and data-model catalog include first-class `org_id` and `user_id` fields, tenant lookup indexes, and legacy-row defaults for pre-existing rows. |
| TC-FV01-038 | unit/performance | Mocked access-token authentication loop reports P95 latency <= 50ms. |
| TC-FV01-039 | unit/security | Default auth service accepts an injected environment token secret and uses distinct runtime secrets when no environment secret is configured. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
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

## 10. Implementation Notes
- Implemented in `src/chatbi/auth.py` using PBKDF2 password hashes and signed HMAC access tokens without adding third-party auth dependencies.
- `PostgresAuthStore` persists organizations, users, refresh sessions, and role audit events in the `auth` schema. `AUTH_TABLES_SQL` is included in the base migration.
- `create_app(..., auth_service=...)` allows tests and production wiring to inject the auth service. `create_app(..., auth_connect=..., use_postgres_metadata=True)` wires the PostgreSQL auth store explicitly. If no environment secret is configured for local development, a per-process runtime secret is generated rather than hard-coded.
- v2 chat requests persist `org_id` in request metadata and runtime query result records.
- RAG v2 documents, chunks, embedding metadata, evidence events, evaluation tables, and v2 guardrail audit events include `org_id` in PostgreSQL schema. RAG repository read methods accept optional `org_id` filters.
- v2 eval run/report and latest release-gate endpoints enforce `admin:eval:write`, `admin:eval:read`, and `admin:release_gate:read`. v2 document indexing enforces `documents:index`.
- v2 document-index tasks include `org_id`; idempotency cache keys are `(endpoint, org_id, idempotency_key)` to prevent cross-tenant task reuse.
- v2 request metadata, runtime query result, and governance trace lookups use tenant checks and return 404 for cross-tenant access to avoid resource-existence leakage.
- v1 management surfaces for document indexing, audit, observability traces, quality dashboard, eval run, and eval report now authenticate real signed tokens and enforce admin permissions. For real tokens, effective user identity comes from the token instead of `user_id` query parameters.
- Evaluation runs are persisted with `org_id`; eval report lookup and latest release-gate summaries are resolved for the authenticated tenant only.
- Role update flows treat cross-tenant targets as not found. Store-level implementations validate the target user's `org_id` before role mutation or audit insertion.
- Access tokens carry `token_version`; role updates increment `auth.users.token_version`, causing previously issued access tokens for that user to fail authentication while refreshed or newly signed-in tokens carry current roles.
- Observability logs sanitize credential-like message fragments and structured attributes (`password`, bearer authorization, access/refresh tokens, API keys, secrets) before records are stored or rendered.
- Auth error responses use generic envelopes and never echo submitted password or token values back to clients.
- Refresh-session HTTP flows rotate refresh tokens on use, reject reused or revoked refresh tokens, and return idempotent revoke responses that do not reveal whether a token hash existed.
- Access tokens use a minimal signed payload containing only documented auth claims; refresh tokens and password material never appear inside access-token payloads.
- Chat history and query detail are filtered by the effective authenticated user. For real signed tokens, v2 history/detail endpoints ignore client-supplied `user_id` and use the token subject.
- v2 analytics results and analytics/document-index tasks carry token-derived `org_id` and `user_id`; task-status and analytics-result lookups return not found when ownership does not match the authenticated context.
- `analytics.results` stores first-class `org_id` and `user_id` columns with tenant lookup indexes, while legacy result rows without those fields map to explicit `org_legacy` and `user_legacy` owners.
- Mocked access-token authentication has a unit performance guard for P95 <= 50ms.
- Default auth service construction accepts `CHATBI_AUTH_TOKEN_SECRET`; when no secret is configured for local runtime construction, each service receives a distinct per-process runtime secret instead of a fixed fallback.
- The legacy `Bearer test-token` remains a local development/test admin token so existing API fixtures continue to work while final-version auth endpoints are introduced.

## 11. First Red-Green Steps
1. Write failing tests for normal user accessing admin trace endpoint.
2. Add `AuthContext` model and fake auth dependency.
3. Add role/permission check helper.
4. Add tenant filter tests for one resource, then apply the pattern to all scoped resources.
