# Spec FV-08: Final Submission Package

Source design:
- [Final roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)
- [Final system design index](../../../system_design/final-version/en/README.en.md)

## 1. Purpose
Define the final artifacts, verification gates, demo script, documentation, and acceptance checklist required for director-level project submission.

## 2. Scope
In scope:
- English and Chinese README, final system design docs, final specs, API docs, startup guide, cloud guide, verification reports, demo script, risks, and next steps.
- Release readiness gate across type checks, tests, security, evals, smoke tests, and human demo acceptance.

Out of scope:
- Legal compliance certification.
- Formal SOC 2 or ISO audit.

## 3. Functional Requirements
| ID | Requirement |
|---|---|
| FR-FV08-001 | The repository MUST include English and Chinese project README files. |
| FR-FV08-002 | The repository MUST include English and Chinese final-version system design docs. |
| FR-FV08-003 | The repository MUST include English and Chinese final-version specs. |
| FR-FV08-004 | API documentation MUST describe auth, chat, RAG, admin, eval, and observability endpoints. |
| FR-FV08-005 | Local startup guide MUST describe required services, env vars, seed, tests, and demo flow. |
| FR-FV08-006 | Cloud deployment guide MUST describe image build, secrets, Kubernetes deployment, smoke tests, and rollback. |
| FR-FV08-007 | Verification report MUST include pyright, pytest, eval gate, security checks, and smoke tests. |
| FR-FV08-008 | Demo script MUST cover user flow and admin flow. |
| FR-FV08-009 | Final risk register MUST document known gaps and next steps. |
| FR-FV08-010 | The React/Vite demo UI MUST render returned `chart_spec` and table rows as an actual chart, not only raw JSON or a table. |

## 4. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-FV08-001 | Final docs MUST use stable relative links. |
| NFR-FV08-002 | Final demo SHOULD be runnable in <= 15 minutes after environment setup. |
| NFR-FV08-003 | Submission package MUST not require real LLM calls for baseline tests. |
| NFR-FV08-004 | All final artifacts MUST be discoverable from the root README. |

## 5. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV08-001 | A reviewer can start from root README and find all final docs, specs, and runbooks. |
| AC-FV08-002 | Machine gates pass: type checks, tests, eval gate, security scan, smoke tests. |
| AC-FV08-003 | Demo script proves sign-in, chat query, RAG citation, admin observability, and release gate. |
| AC-FV08-004 | Risks and not-yet-production items are explicit, not hidden. |
| AC-FV08-005 | English and Chinese final-version docs are both present. |
| AC-FV08-006 | A chart query such as `Plot monthly revenue for 2012` displays a chart in the local React UI when the API returns `chart_spec`. |

## 6. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-FV08-001 | docs | Link check over README, final system design, and final specs. |
| TC-FV08-002 | ci | Run pyright and pytest commands documented in README. |
| TC-FV08-003 | eval | Run release gate with passing and failing fixtures. |
| TC-FV08-004 | security | Run secret scan and verify no plaintext secrets are committed. |
| TC-FV08-005 | smoke | Run local or staging smoke test. |
| TC-FV08-006 | human acceptance | Follow demo script and record pass/fail notes. |
| TC-FV08-007 | docs parity | Verify English and Chinese final-version doc sets contain matching numbered files. |
| TC-FV08-008 | frontend | React/Vite source renders `chart_spec` through a visible SVG chart component. |

Implemented test coverage:
- `tests/test_final_submission_package.py`

Implemented submission artifacts:
- `README.md`
- `docs/api.md`
- `docs/local-startup.md`
- `docs/deployment/cloud-kubernetes-runbook.md`
- `docs/demo-script.md`
- `docs/risk-register.md`
- `verification/12-final-submission-package-verification.md`
- `spec/final-version/en/README.en.md`
- `spec/final-version/zh-CN/README.zh-CN.md`
- `system_design/final-version/en/README.en.md`
- `system_design/final-version/zh-CN/README.zh-CN.md`

Implemented evidence:
- `FR-FV08-001` through `FR-FV08-003`: Root README links English/Chinese README, final-version specs, and final-version system design indexes.
- `FR-FV08-004`: `docs/api.md` covers auth, chat, RAG/documents, admin, eval, and observability endpoints.
- `FR-FV08-005`: `docs/local-startup.md` documents services, env vars, seed, tests, and demo flow.
- `FR-FV08-006`: `docs/deployment/cloud-kubernetes-runbook.md` documents image build, secrets, Kubernetes deployment, smoke tests, and rollback.
- `FR-FV08-007`: `verification/12-final-submission-package-verification.md` lists pyright, pytest, eval gate, security scan, smoke tests, and baseline mock LLM policy.
- `FR-FV08-008`: `docs/demo-script.md` covers sign-in, chat query, RAG citation, admin observability, and release gate.
- `FR-FV08-009`: `docs/risk-register.md` documents known gaps and next steps.
- `NFR-FV08-001`: `tests/test_final_submission_package.py` validates final Markdown links are relative and resolve to existing local files or directories.

## 7. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
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
| FR-FV08-010 | AC-FV08-006 | TC-FV08-008 |
