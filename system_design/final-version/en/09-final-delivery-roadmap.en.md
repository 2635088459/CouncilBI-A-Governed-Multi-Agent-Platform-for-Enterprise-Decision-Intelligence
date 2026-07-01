# 09 Final Delivery Roadmap

## 1. Overall Roadmap

The project already has the core ChatBI skeleton. The next phase should follow production dependencies rather than opening all workstreams at once.

Recommended order:

1. Auth/RBAC/Tenant.
2. LLM Gateway.
3. Embedding and Vector RAG.
4. Data seed and migrations.
5. Admin observability.
6. Resilience.
7. Cloud/Kubernetes.
8. Final demo and release package.

## 2. Phase 1: Users and Permissions

Goals:

1. Users can sign up and sign in.
2. APIs can identify user/org/role.
3. Admin-only endpoints reject normal users.
4. Query history and traces are tenant-scoped.

Acceptance:

1. Normal users get 403 on admin endpoints.
2. Tenant A cannot see tenant B data.
3. Every chat query has user/org trace context.

## 3. Phase 2: LLM Gateway

Goals:

1. Connect a real LLM API.
2. Keep a mock provider for tests.
3. Track token, cost, and latency.
4. Support timeout and retry.

Acceptance:

1. Tests run with the mock provider.
2. Real model calls work when an API key is configured.
3. Observability shows model tokens and latency.

## 4. Phase 3: Embedding and Vector RAG

Goals:

1. Documents can be chunked.
2. Chunks can be embedded.
3. Vectors can be stored and searched.
4. RAG answers include citations.
5. Retrieval is tenant-filtered.

Acceptance:

1. Seeded or uploaded documents are searchable.
2. Tenant A cannot retrieve tenant B documents.
3. The system does not invent answers when evidence is missing.

## 5. Phase 4: Data Platform and Test Data

Goals:

1. Migrations manage schema.
2. Seed supports small, medium, and large datasets.
3. Business data and document evidence are connected.
4. Evaluation sets cover representative questions.

Acceptance:

1. One command can rebuild local demo data.
2. CI can run small seed.
3. Medium seed supports local integration testing.
4. Large seed supports load testing.

## 6. Phase 5: Admin Observability

Goals:

1. Admins can view traces, evals, and release gates.
2. Normal users cannot view internal system state.
3. Sensitive logs are masked.
4. Security events are audited.

Acceptance:

1. Admin dashboard shows Spec 10 outputs.
2. Authorization tests cover admin-only APIs.
3. Failed release gates can block release.

## 7. Phase 6: Resilience and Load Testing

Goals:

1. LLM, DB, and vector search have timeouts.
2. LLM calls have retry/backoff.
3. External dependencies have circuit breakers.
4. API has rate limits.
5. Long tasks use queues.

Acceptance:

1. Mock LLM timeout triggers safe degradation.
2. High concurrency does not consume unbounded resources.
3. Load-test reports include P50/P95/P99 latency.

## 8. Phase 7: Cloud and Kubernetes

Goals:

1. Docker images can be built.
2. Kubernetes manifests deploy the app.
3. Cloud PostgreSQL/Redis/secrets are configurable.
4. Staging is reachable.
5. CI/CD can test and deploy.

Acceptance:

1. Staging URL works.
2. Health checks pass.
3. HPA and resource limits exist.
4. Secrets are not committed to git.

## 9. Phase 8: Final Submission Package

The final package should include:

1. English and Chinese README.
2. Final-version system design docs.
3. API documentation.
4. Local startup guide.
5. Cloud deployment guide.
6. Test and evaluation reports.
7. Demo script.
8. Architecture diagrams.
9. Risks and next steps.

## 10. Recommended Next Step

The next implementation step should be Phase 1: Auth/RBAC/Tenant Isolation.

It is the foundation for LLM access, RAG access, admin observability, and cloud deployment.
