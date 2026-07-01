# 00 Executive System Design

## 1. Project Positioning

This project is a Governed Multi-Agent ChatBI Platform for enterprise decision intelligence. It is not a simple chatbot and not just an NL2SQL demo. It combines natural-language analytics, a business semantic layer, SQL safety governance, RAG-based evidence, analytics and forecasting, evaluation gates, and observability.

In plain language: a business user asks a question, and the system decomposes it into query, analysis, explanation, verification, and audit steps before returning a traceable answer.

## 2. What the Final Version Must Prove

The final version should prove that:

1. The platform can serve multiple real users.
2. It can call real LLMs without delegating all control to prompts.
3. It has security boundaries for SQL, data access, and sensitive fields.
4. It is observable enough to debug latency, failures, and quality regressions.
5. It has evaluation and release gates instead of subjective quality checks.
6. It can be deployed to cloud infrastructure with Kubernetes and secrets.

## 3. Current MVP Capabilities

The repository already includes:

1. ChatBI API and application entry points.
2. Orchestrator and multi-agent structure.
3. SQL Guardrail and governance foundation.
4. RAG worker/service/indexing modules.
5. Analytics and forecasting modules.
6. Evaluation, trace, metrics, release gate, and observability backend capabilities.
7. README and v2 system design documentation.

This means the platform skeleton is already in place.

## 4. Final-Version Gaps

The remaining industrial-grade gaps are:

1. Auth: sign-up, sign-in, tokens, sessions, password safety.
2. RBAC: separate normal users, analysts, and admins.
3. Tenant isolation: data, traces, documents, and audits must be scoped by organization.
4. LLM Gateway: a single controlled interface for model providers.
5. Embeddings and vector database: real RAG retrieval.
6. Admin Console: controlled access to evals, traces, audits, and release gates.
7. Data seed: large repeatable business, document, evaluation, and load-test data.
8. Resilience: circuit breakers, retries, timeouts, queues, and degradation.
9. Cloud/Kubernetes: deployments, ingress, secrets, scaling, and CI/CD.

## 5. Architecture Principles

### Principle 1: The LLM is a capability, not the system boundary

The model can understand, generate, and summarize. Permissions, safety, auditing, and metric definitions must remain controlled by backend systems.

### Principle 2: Every critical action must be traceable

For each user question, the system should know who asked it, which organization it belongs to, which agents ran, what SQL was generated, whether guardrails allowed it, which model was called, how much it cost, and whether the result passed validation.

### Principle 3: User and admin views must be separated

Normal users see their own questions and authorized data. Admins see system health, traces, evals, release gates, audit logs, and security events.

### Principle 4: Build boundaries before optimizing intelligence

In an industrial project, permissions, isolation, auditability, deployment, and rollback are as important as model quality.

## 6. Final Delivery Shape

The final project should include:

1. A Docker Compose local environment.
2. Kubernetes manifests or Helm charts.
3. Configurable LLM providers.
4. Configurable embedding/vector backends.
5. Repeatable seed and evaluation data.
6. API and system design documentation.
7. Tests, evaluation jobs, and release gates.
8. Demo scripts for both user and admin workflows.
