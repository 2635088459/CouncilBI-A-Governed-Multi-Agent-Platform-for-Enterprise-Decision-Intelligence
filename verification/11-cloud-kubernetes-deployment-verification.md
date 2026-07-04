# FV-07 Cloud Kubernetes Deployment Verification

## Scope

This verification covers Docker image build contracts, Kubernetes deployment
manifests, secret handling, resource limits, HPA, CI/CD, staging smoke commands,
and rollback readiness.

## Evidence

| Requirement | Status | Evidence |
|---|---|---|
| `FR-FV07-001` | Covered | `Dockerfile.backend`, `Dockerfile.worker`, `Dockerfile.frontend`, `tests/test_dockerfiles.py` |
| `FR-FV07-002` | Covered | `k8s/chatbi-runtime.yaml`, `tests/test_k8s_runtime_architecture.py` |
| `FR-FV07-003` | Covered | `/healthz`, `/readyz`, `tests/test_runtime_probes.py`, `tests/test_runtime_latency_smoke.py` |
| `FR-FV07-004` | Covered | `secretKeyRef` usage in Kubernetes manifest, required env placeholders in Compose/init scripts, and `tests/test_cloud_secret_scan.py` |
| `FR-FV07-005` | Covered | Resource requests/limits in each deployment and backend HPA |
| `FR-FV07-006` | Covered as config contract | `chatbi-managed-service-config` and runtime secret references support managed PostgreSQL/Redis endpoints |
| `FR-FV07-007` | Covered | `.github/workflows/fv07-cloud-deployment.yml` runs tests, image builds, release gate, optional staging deploy, and smoke tests |
| `FR-FV07-008` | Covered | Runbook and workflow include `kubectl rollout undo` rollback commands |

## Verification Commands

```bash
python -m pyright tests/test_cloud_deployment_workflow.py tests/test_dockerfiles.py tests/test_k8s_runtime_architecture.py tests/test_cloud_deployment_runbook.py tests/test_cloud_secret_scan.py
python -m pytest tests/test_cloud_deployment_workflow.py tests/test_dockerfiles.py tests/test_k8s_runtime_architecture.py tests/test_docker_compose_architecture.py tests/test_runtime_probes.py tests/test_runtime_latency_smoke.py tests/test_cloud_deployment_runbook.py tests/test_cloud_secret_scan.py
```

## Staging Notes

The repository does not commit staging credentials. Operators must create
`chatbi-runtime-secrets` from a cloud secret manager or deployment-time
environment variables before applying manifests.

Rollback is performed with Kubernetes rollout history and `kubectl rollout undo`,
followed by `/healthz` and `/readyz` smoke checks.
