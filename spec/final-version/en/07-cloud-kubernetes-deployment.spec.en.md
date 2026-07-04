# Spec FV-07: Cloud and Kubernetes Deployment

Source design:
- [Cloud and Kubernetes design](../../../system_design/final-version/en/06-cloud-kubernetes-deployment.en.md)
- [Final roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)

## 1. Purpose
Define the Docker, Kubernetes, cloud configuration, CI/CD, and smoke-test requirements for staging and production deployment readiness.

## 2. Scope
In scope:
- Docker image build, Kubernetes manifests or Helm chart, ingress, health checks, secrets, resource limits, HPA.
- Staging deployment, smoke tests, CI/CD gates, rollback readiness.

Out of scope:
- Full multi-cloud abstraction.
- Production cost optimization beyond basic resource limits.

## 3. Functional Requirements
| ID | Requirement |
|---|---|
| FR-FV07-001 | The backend, worker, and frontend images MUST be buildable from source. |
| FR-FV07-002 | Kubernetes manifests MUST define deployments, services, config, secrets references, and ingress. |
| FR-FV07-003 | Runtime services MUST expose liveness and readiness probes. |
| FR-FV07-004 | Secrets MUST be provided by Kubernetes Secret or cloud secret manager, not committed files. |
| FR-FV07-005 | Deployments MUST define resource requests and limits. |
| FR-FV07-006 | Staging environment MUST support managed PostgreSQL/Redis configuration. |
| FR-FV07-007 | CI/CD MUST run tests, build images, run release gate, deploy staging, and run smoke tests. |
| FR-FV07-008 | Release process MUST support rollback or redeploying previous image. |

## 4. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-FV07-001 | Health endpoints SHOULD respond P99 <= 200ms in staging smoke tests. |
| NFR-FV07-002 | Manifests MUST not include plaintext API keys, passwords, or tokens. |
| NFR-FV07-003 | Staging deploy SHOULD be reproducible from documented commands. |
| NFR-FV07-004 | HPA or scaling policy MUST exist for API service before production submission. |

## 5. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV07-001 | Docker images build successfully in CI. |
| AC-FV07-002 | Kubernetes manifests pass validation and deploy to staging. |
| AC-FV07-003 | Staging `/healthz` and `/readyz` pass smoke tests. |
| AC-FV07-004 | Secret scan confirms no committed provider keys or database passwords. |
| AC-FV07-005 | Resource limits, probes, ingress, and HPA/scaling config are present. |

## 6. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-FV07-001 | build | Build backend, worker, and frontend Docker images. |
| TC-FV07-002 | static | Validate Kubernetes YAML schema and required fields. |
| TC-FV07-003 | security | Secret scanning rejects committed secrets. |
| TC-FV07-004 | deploy | Deploy manifests to local cluster or staging namespace. |
| TC-FV07-005 | smoke | Call `/healthz`, `/readyz`, and one authenticated API path. |
| TC-FV07-006 | config | Verify staging can connect to configured PostgreSQL and Redis. |
| TC-FV07-007 | release | Rollback procedure is documented and smoke-tested at least once. |

Implemented test coverage:
- `tests/test_cloud_deployment_workflow.py`
- `tests/test_cloud_deployment_runbook.py`
- `tests/test_cloud_secret_scan.py`
- `tests/test_dockerfiles.py`
- `tests/test_docker_compose_architecture.py`
- `tests/test_k8s_runtime_architecture.py`

Implemented deployment artifacts:
- `.github/workflows/fv07-cloud-deployment.yml`
- `docs/deployment/cloud-kubernetes-runbook.md`
- `verification/11-cloud-kubernetes-deployment-verification.md`
- `Dockerfile.backend`
- `Dockerfile.worker`
- `Dockerfile.frontend`
- `.dockerignore`
- `docker-compose.yml`
- `docker/postgres/init/01-readonly-role.sh`
- `k8s/chatbi-runtime.yaml`

Implemented evidence:
- `FR-FV07-001`: Backend, worker, and frontend Dockerfiles build from repository source; the frontend image builds static assets with `chatbi-build-frontend` and serves them with nginx.
- `FR-FV07-002`: The manifest defines backend, frontend, worker, Redis, PostgreSQL, services, config maps, secret references, and ingress routes.
- `FR-FV07-003`: Backend exposes `/healthz` liveness and `/readyz` readiness probes; Redis and PostgreSQL expose dependency readiness probes.
- `FR-FV07-004` / `NFR-FV07-002`: Database credentials are referenced through `secretKeyRef` (`chatbi-runtime-secrets`) or required environment placeholders. `tests/test_cloud_secret_scan.py` rejects committed provider keys, database passwords, plaintext database URLs, and token fragments across deployment artifacts.
- `FR-FV07-005` / `NFR-FV07-004`: Deployments define resource requests/limits and the backend API has a `HorizontalPodAutoscaler`.
- `FR-FV07-006`: `chatbi-managed-service-config` and `chatbi-runtime-secrets` support managed PostgreSQL and Redis staging endpoints without committing credentials.
- `FR-FV07-007`: `.github/workflows/fv07-cloud-deployment.yml` runs type checks, deployment tests, Docker image builds, release-gate tests, optional staging deployment, and smoke tests.
- `FR-FV07-008`: The staging workflow and runbook document `kubectl rollout undo` commands for backend, frontend, and worker.
- `NFR-FV07-001`: Staging smoke commands call `/healthz` and `/readyz`; local P99 coverage is provided by `tests/test_runtime_latency_smoke.py`.
- `NFR-FV07-003`: `docs/deployment/cloud-kubernetes-runbook.md` documents reproducible build, secret creation, deploy, smoke, and rollback commands.

## 7. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-FV07-001 | AC-FV07-001 | TC-FV07-001 |
| FR-FV07-002 | AC-FV07-002 | TC-FV07-002, TC-FV07-004 |
| FR-FV07-003 | AC-FV07-003 | TC-FV07-005 |
| FR-FV07-004 | AC-FV07-004 | TC-FV07-003 |
| FR-FV07-005 | AC-FV07-005 | TC-FV07-002 |
| FR-FV07-006 | AC-FV07-003 | TC-FV07-006 |
| FR-FV07-007 | AC-FV07-001 | TC-FV07-001, TC-FV07-005 |
| FR-FV07-008 | AC-FV07-005 | TC-FV07-007 |
