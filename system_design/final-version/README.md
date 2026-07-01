# Final Version System Design

This folder contains the final-version system design package for the Governed Multi-Agent ChatBI Platform.

The folder is split by language:

- Chinese: [zh-CN/README.zh-CN.md](zh-CN/README.zh-CN.md)
- English: [en/README.en.md](en/README.en.md)

The final-version documents are the production-readiness blueprint for the project. They extend the earlier v2 module designs with authentication, RBAC, tenant isolation, real LLM API integration, embeddings and vector search, admin-only observability, cloud deployment, Kubernetes, resilience, load testing, and the final delivery roadmap.

## Structure

```text
final-version/
  README.md
  zh-CN/
    README.zh-CN.md
    00-executive-system-design.zh-CN.md
    ...
  en/
    README.en.md
    00-executive-system-design.en.md
    ...
```

Recommended next implementation phase: Auth, RBAC, and tenant isolation.
