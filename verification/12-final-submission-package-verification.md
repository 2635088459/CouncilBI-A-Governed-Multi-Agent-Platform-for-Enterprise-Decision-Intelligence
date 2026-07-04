# FV-08 Final Submission Package Verification

## Scope

This verification confirms that final artifacts are discoverable, bilingual
final-version docs/specs are present, baseline gates avoid real LLM calls, and
the demo package covers user and admin flows.

## Evidence

| Requirement | Status | Evidence |
|---|---|---|
| `FR-FV08-001` | Covered | `README.md`, `docs/readme/README.en.md`, `docs/readme/README.zh-CN.md` |
| `FR-FV08-002` | Covered | `system_design/final-version/en/`, `system_design/final-version/zh-CN/` |
| `FR-FV08-003` | Covered | `spec/final-version/en/`, `spec/final-version/zh-CN/` |
| `FR-FV08-004` | Covered | `docs/api.md` |
| `FR-FV08-005` | Covered | `docs/local-startup.md` |
| `FR-FV08-006` | Covered | `docs/deployment/cloud-kubernetes-runbook.md` |
| `FR-FV08-007` | Covered | This report plus release gate, secret scan, runtime smoke, and full pytest commands |
| `FR-FV08-008` | Covered | `docs/demo-script.md` |
| `FR-FV08-009` | Covered | `docs/risk-register.md` |
| `NFR-FV08-001` | Covered | `tests/test_final_submission_package.py` validates relative links and local target existence |

## Verification Commands

```bash
.venv313/bin/pyright tests/test_final_submission_package.py
.venv313/bin/python -m pytest tests/test_final_submission_package.py
.venv313/bin/python -m pytest tests/test_release_gate.py tests/test_release_gate_ci.py
.venv313/bin/python -m pytest tests/test_cloud_secret_scan.py tests/test_runtime_latency_smoke.py
.venv313/bin/python -m pytest
```

## Baseline LLM Policy

The baseline test suite uses mock/deterministic providers. The optional OpenAI
smoke test is skipped unless `OPENAI_API_KEY` is present.
