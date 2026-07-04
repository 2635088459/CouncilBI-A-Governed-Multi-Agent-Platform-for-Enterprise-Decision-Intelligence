# Governed Multi-Agent ChatBI Platform

Enterprise decision intelligence platform for natural-language BI, governed SQL, multi-agent analytics, RAG evidence retrieval, and release-gated observability.

This repository is being upgraded from a course-style engineering project into an industry-facing final version suitable for executive review, cloud deployment planning, and production-readiness hardening.

## Read The Full README

- [English README](docs/readme/README.en.md)
- [中文 README](docs/readme/README.zh-CN.md)
- [Final Submission Checklist](verification/12-final-submission-package-verification.md)

## Final Submission Package

| Artifact | Link |
|---|---|
| Final specs index | [spec/final-version/README.md](spec/final-version/README.md) |
| English final specs | [spec/final-version/en/README.en.md](spec/final-version/en/README.en.md) |
| Chinese final specs | [spec/final-version/zh-CN/README.zh-CN.md](spec/final-version/zh-CN/README.zh-CN.md) |
| English final system design | [system_design/final-version/en/README.en.md](system_design/final-version/en/README.en.md) |
| Chinese final system design | [system_design/final-version/zh-CN/README.zh-CN.md](system_design/final-version/zh-CN/README.zh-CN.md) |
| API documentation | [docs/api.md](docs/api.md) |
| Local startup guide | [docs/local-startup.md](docs/local-startup.md) |
| Cloud deployment guide | [docs/deployment/cloud-kubernetes-runbook.md](docs/deployment/cloud-kubernetes-runbook.md) |
| Demo script | [docs/demo-script.md](docs/demo-script.md) |
| Risk register | [docs/risk-register.md](docs/risk-register.md) |
| Verification reports | [verification/](verification/) |

## Current Status

The project currently has a production-oriented MVP foundation:

- versioned v2 specs and system design documents
- backend API contracts and FastAPI routes
- multi-agent orchestration
- semantic layer and governed SQL guardrails
- RAG architecture and indexing workflow foundations
- deterministic analytics and forecasting MVP
- evaluation runner, release gate, observability, JSON logs, trace detail, and metrics
- Docker Compose runtime with React + Vite frontend, backend, worker, PostgreSQL, and Redis images
- Kubernetes runtime scaffold
- spec-10 GitHub Actions release gate

It is not yet a full production SaaS deployment. The final version still needs real LLM provider integration, authentication/RBAC, production vector search, cloud-managed infrastructure, large-scale seed data, and distributed resilience hardening.

## Baseline Verification

Baseline tests use mock/deterministic providers and do not require real LLM calls.

```bash
.venv313/bin/python -m pytest
```
