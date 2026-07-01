# Governed Multi-Agent ChatBI Platform

Enterprise decision intelligence platform for natural-language BI, governed SQL, multi-agent analytics, RAG evidence retrieval, and release-gated observability.

This repository is being upgraded from a course-style engineering project into an industry-facing final version suitable for executive review, cloud deployment planning, and production-readiness hardening.

## Read The Full README

- [English README](docs/readme/README.en.md)
- [中文 README](docs/readme/README.zh-CN.md)

## Current Status

The project currently has a production-oriented MVP foundation:

- versioned v2 specs and system design documents
- backend API contracts and FastAPI routes
- multi-agent orchestration
- semantic layer and governed SQL guardrails
- RAG architecture and indexing workflow foundations
- deterministic analytics and forecasting MVP
- evaluation runner, release gate, observability, JSON logs, trace detail, and metrics
- Docker Compose scaffold
- Kubernetes runtime scaffold
- spec-10 GitHub Actions release gate

It is not yet a full production SaaS deployment. The final version still needs real LLM provider integration, authentication/RBAC, production vector search, cloud-managed infrastructure, large-scale seed data, and distributed resilience hardening.

## Recommended Next Step

Create the final production readiness plan:

```text
verification/final-version-readiness.md
```

That document should turn the final-version roadmap into epics, blockers, priorities, acceptance criteria, and implementation order.
