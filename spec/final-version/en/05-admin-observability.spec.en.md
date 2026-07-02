# Spec FV-05: Admin Observability

Source design:
- [Security and Admin Observability design](../../../system_design/final-version/en/08-security-observability-admin.en.md)
- [Final roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)

## 1. Purpose
Define admin-only access to observability, evaluation, audit, and release-gate capabilities created by Spec 10.

## 2. Scope
In scope:
- Admin authorization for traces, metrics, eval reports, release gates, audit events, and security events.
- User/org context in logs, traces, and audit records.
- Sensitive data masking and admin dashboard API contracts.

Out of scope:
- Building a full commercial APM product.
- Replacing cloud-native observability tools.

## 3. Functional Requirements
| ID | Requirement |
|---|---|
| FR-FV05-001 | Trace, eval, audit, and release-gate APIs MUST require admin permission. |
| FR-FV05-002 | Observability records MUST include `trace_id`, `user_id`, and `org_id` when request-scoped. |
| FR-FV05-003 | Admin access to sensitive observability data MUST itself be audited. |
| FR-FV05-004 | Logs MUST mask passwords, tokens, secrets, and configured PII fields. |
| FR-FV05-005 | Admin dashboard APIs MUST expose system health, LLM health, SQL safety, RAG health, evals, release gate, and audit events. |
| FR-FV05-006 | Release gate failure MUST be visible to admins and block final release workflow. |
| FR-FV05-007 | Normal users MUST never see global traces, evals, release gates, or audit events. |

## 4. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-FV05-001 | Admin dashboard summary endpoint SHOULD respond P95 <= 500ms locally with 10k mock events. |
| NFR-FV05-002 | Logs MUST be structured JSON for request-scoped events. |
| NFR-FV05-003 | Audit records MUST be append-only from the application perspective. |
| NFR-FV05-004 | Observability queries MUST be tenant-scoped unless caller has global admin permission. |

## 5. Contracts
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

## 6. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV05-001 | Admin can view traces, eval report, release gate status, and audit summary. |
| AC-FV05-002 | Normal users receive 403 for all admin observability endpoints. |
| AC-FV05-003 | Admin reads of sensitive observability endpoints create audit events. |
| AC-FV05-004 | Logs and traces include user/org context without leaking secrets. |
| AC-FV05-005 | Failed release gate blocks release workflow. |

## 7. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-FV05-001 | integration | Admin reads dashboard summary successfully. |
| TC-FV05-002 | integration negative | Normal user reads trace/eval/release gate and receives 403. |
| TC-FV05-003 | audit | Admin trace read writes audit event. |
| TC-FV05-004 | security | Log masking removes token/password/secret values. |
| TC-FV05-005 | release | Failed release gate stops release command or CI job. |
| TC-FV05-006 | tenant | Tenant admin cannot read another tenant's observability data. |
| TC-FV05-007 | benchmark | Dashboard summary P95 over 10k mock events. |

## 8. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-FV05-001 | AC-FV05-002 | TC-FV05-002 |
| FR-FV05-002 | AC-FV05-004 | TC-FV05-004 |
| FR-FV05-003 | AC-FV05-003 | TC-FV05-003 |
| FR-FV05-004 | AC-FV05-004 | TC-FV05-004 |
| FR-FV05-005 | AC-FV05-001 | TC-FV05-001 |
| FR-FV05-006 | AC-FV05-005 | TC-FV05-005 |
| FR-FV05-007 | AC-FV05-002 | TC-FV05-002 |

