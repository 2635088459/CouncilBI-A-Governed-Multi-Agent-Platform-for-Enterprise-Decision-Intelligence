# Cloud Kubernetes Deployment Runbook

This runbook documents the reproducible staging deployment path for FV-07.
Commands use placeholders so secrets are injected at deploy time and never
committed.

## 1. Build Images

```bash
IMAGE_TAG="$(git rev-parse --short HEAD)"
docker build -f Dockerfile.backend -t "$REGISTRY/governed-chatbi-backend:$IMAGE_TAG" .
docker build -f Dockerfile.worker -t "$REGISTRY/governed-chatbi-worker:$IMAGE_TAG" .
docker build -f Dockerfile.frontend -t "$REGISTRY/governed-chatbi-frontend:$IMAGE_TAG" .
docker push "$REGISTRY/governed-chatbi-backend:$IMAGE_TAG"
docker push "$REGISTRY/governed-chatbi-worker:$IMAGE_TAG"
docker push "$REGISTRY/governed-chatbi-frontend:$IMAGE_TAG"
```

## 2. Create Runtime Secrets

`DATABASE_URL`, `POSTGRES_PASSWORD`, `OPENAI_API_KEY`, and auth token secrets must
come from a cloud secret manager or operator-provided environment variables.
Do not commit generated Secret manifests, shell history exports, or `.env`
files that contain these values.

```bash
kubectl create namespace chatbi --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic chatbi-runtime-secrets \
  --namespace chatbi \
  --from-literal=DATABASE_URL="$DATABASE_URL" \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=CHATBI_AUTH_TOKEN_SECRET="$CHATBI_AUTH_TOKEN_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -
```

For GKE, keep Google Secret Manager as the source of truth and hydrate the
Kubernetes Secret at deploy time:

```bash
gcloud secrets versions access latest --secret=chatbi-database-url > /tmp/chatbi-database-url
gcloud secrets versions access latest --secret=chatbi-postgres-password > /tmp/chatbi-postgres-password
gcloud secrets versions access latest --secret=chatbi-openai-api-key > /tmp/chatbi-openai-api-key
gcloud secrets versions access latest --secret=chatbi-auth-token-secret > /tmp/chatbi-auth-token-secret

kubectl create namespace chatbi --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic chatbi-runtime-secrets \
  --namespace chatbi \
  --from-file=DATABASE_URL=/tmp/chatbi-database-url \
  --from-file=POSTGRES_PASSWORD=/tmp/chatbi-postgres-password \
  --from-file=OPENAI_API_KEY=/tmp/chatbi-openai-api-key \
  --from-file=CHATBI_AUTH_TOKEN_SECRET=/tmp/chatbi-auth-token-secret \
  --dry-run=client -o yaml | kubectl apply -f -
```

Only the backend and worker deployments reference `OPENAI_API_KEY`; the frontend
receives only API routing configuration.

## 3. Configure Managed Services

Set `REDIS_URL` in `k8s/chatbi-runtime.yaml` or an environment overlay to the
managed Redis endpoint. `DATABASE_URL` stays in `chatbi-runtime-secrets`, not in
the manifest.

For staging, use a dedicated managed PostgreSQL database, managed Redis
instance, and isolated secret namespace.

Set non-secret LLM configuration in `chatbi-runtime-config`, for example
`CHATBI_LLM_PROVIDER=openai` and `CHATBI_LLM_MODEL=gpt-4o-mini`. Keep provider
keys in `chatbi-runtime-secrets`.

## 4. Deploy Staging

```bash
kubectl apply -f k8s/chatbi-runtime.yaml
kubectl rollout status deployment/backend -n chatbi --timeout=180s
kubectl rollout status deployment/frontend -n chatbi --timeout=180s
kubectl rollout status deployment/worker -n chatbi --timeout=180s
```

## 5. Smoke Test

Health checks should remain below 200ms P99 during staging smoke. The local
latency check is:

```bash
python -m pytest tests/test_runtime_latency_smoke.py
```

Staging smoke:

```bash
curl --fail --max-time 2 "$STAGING_BASE_URL/healthz"
curl --fail --max-time 2 "$STAGING_BASE_URL/readyz"
curl --fail --max-time 5 \
  -H "Authorization: Bearer $STAGING_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: trc_staging_smoke" \
  -d '{"request_id":"req_staging_smoke","session_id":"ses_staging_smoke","user_id":"u_staging","role":"business_user","locale":"en","question":"Show revenue trend."}' \
  "$STAGING_BASE_URL/api/v2/chat/query"
```

## 6. Rollback

Use Kubernetes rollout history to inspect prior revisions, then roll back the
affected workload and re-run smoke tests.

```bash
kubectl rollout history deployment/backend -n chatbi
kubectl rollout undo deployment/backend -n chatbi
kubectl rollout undo deployment/frontend -n chatbi
kubectl rollout undo deployment/worker -n chatbi
kubectl rollout status deployment/backend -n chatbi --timeout=180s
curl --fail --max-time 2 "$STAGING_BASE_URL/healthz"
curl --fail --max-time 2 "$STAGING_BASE_URL/readyz"
```
