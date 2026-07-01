# 06 Cloud and Kubernetes Deployment

## 1. Deployment Goal

The final project should be deployable to AWS or Google Cloud. Application services should run on Kubernetes, while databases, cache, and object storage should prefer managed cloud services.

In simple terms: we manage the business services; the cloud provider manages the heavy infrastructure.

## 2. Cloud Components

### Application Runtime

1. Kubernetes: EKS or GKE.
2. Ingress Controller: HTTPS entry point.
3. Container Registry: Docker image storage.
4. HPA: horizontal scaling.

### Data Layer

1. Managed PostgreSQL: RDS or Cloud SQL.
2. Managed Redis: ElastiCache or Memorystore.
3. Object Storage: S3 or GCS.
4. Vector DB: pgvector or an external vector service.

### Security and Configuration

1. Kubernetes Secrets for basic configuration.
2. Cloud Secret Manager for production.
3. TLS certificates.
4. IAM or service accounts.

## 3. Kubernetes Workloads

Recommended deployments:

1. `web`
2. `api`
3. `worker`
4. `llm-gateway`
5. `admin`

Each deployment should define:

1. Resource requests and limits.
2. Readiness probes.
3. Liveness probes.
4. Environment configuration.
5. Secret references.
6. Structured logging.

## 4. Environments

Use at least:

1. `local`
2. `staging`
3. `production`

Each environment should have separate databases, secrets, model budgets, rate limits, and dashboards.

## 5. CI/CD Flow

Recommended flow:

1. Pull request triggers unit tests.
2. Run type checks.
3. Build Docker images.
4. Run eval/release gate.
5. Push image to registry.
6. Deploy to staging.
7. Run smoke tests.
8. Manually approve production deploy.

## 6. Release Strategy

Use rolling updates by default. Use canaries for model and prompt changes. Roll back when release gates or critical metrics fail.

Model and prompt changes should be evaluated, not treated as ordinary code-only releases.

## 7. Directory Recommendation

```text
deploy/
  kubernetes/
    base/
      api-deployment.yaml
      worker-deployment.yaml
      web-deployment.yaml
      service.yaml
      ingress.yaml
    overlays/
      local/
      staging/
      production/
```

This can later become a Helm chart.

## 8. Implementation Order

1. Stabilize Dockerfile and Compose.
2. Add Kubernetes base manifests.
3. Add Postgres/Redis secrets.
4. Test locally with kind or minikube.
5. Deploy to GKE/EKS staging.
6. Add ingress and TLS.
7. Add HPA and resource limits.
8. Add CI/CD deployment.
