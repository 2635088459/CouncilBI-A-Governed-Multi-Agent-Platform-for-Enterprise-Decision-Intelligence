# 06 云端与 Kubernetes 部署

## 1. 部署目标

最终项目应该能部署到 AWS 或 Google Cloud。为了简洁和可迁移，应用层使用 Kubernetes，数据库、缓存和对象存储尽量使用云厂商托管服务。

大白话：我们自己管业务服务，数据库这类重基础设施优先交给云厂商托管。

## 2. 云端组件

### 2.1 应用运行

1. Kubernetes：EKS 或 GKE。
2. Ingress Controller：对外暴露 HTTPS。
3. Container Registry：保存 Docker 镜像。
4. Horizontal Pod Autoscaler：按 CPU 或请求量扩缩容。

### 2.2 数据层

1. Managed PostgreSQL：RDS 或 Cloud SQL。
2. Managed Redis：ElastiCache 或 Memorystore。
3. Object Storage：S3 或 GCS。
4. Vector DB：pgvector on PostgreSQL，或独立向量服务。

### 2.3 安全与配置

1. Kubernetes Secret：短期可以使用。
2. Cloud Secret Manager：正式环境推荐。
3. TLS Certificate：HTTPS。
4. IAM / Service Account：服务访问云资源。

## 3. Kubernetes 工作负载

建议至少拆这些 Deployment：

1. `web`：前端。
2. `api`：后端 API。
3. `worker`：异步任务、评估、RAG indexing。
4. `llm-gateway`：模型调用入口，可先和 API 合并。
5. `admin`：Admin Console，可先和 web 合并。

每个 Deployment 需要：

1. requests/limits。
2. readiness probe。
3. liveness probe。
4. environment config。
5. secret reference。
6. structured logging。

## 4. 环境划分

至少三个环境：

1. `local`：开发环境。
2. `staging`：上线前验证。
3. `production`：正式环境。

不同环境要有不同：

1. 数据库。
2. secrets。
3. 模型预算。
4. rate limit。
5. observability dashboard。

## 5. CI/CD 流程

推荐流程：

1. Pull Request 触发单元测试。
2. 触发类型检查。
3. 构建 Docker 镜像。
4. 运行 eval/release gate。
5. 推送镜像到 registry。
6. 部署到 staging。
7. smoke test。
8. 手动批准后部署 production。

最终实现必须从 React + Vite 工程构建真实浏览器前端镜像，不能再使用
inline placeholder 页面。本地 Compose 手动测试前，需要构建 frontend、backend、
worker 三个应用镜像。

## 6. 发布策略

建议使用：

1. Rolling Update：默认安全发布。
2. Canary：对 LLM prompt 或模型变化更适合。
3. Rollback：release gate 或关键指标失败时回滚。

LLM/prompt 变化不能只当普通代码发布，要跑评估集。

## 7. Kubernetes 资源目录建议

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

也可以后续升级为 Helm chart。

## 8. 实施顺序

1. 确认 Dockerfile 和 Compose 可以稳定启动，并包含 React + Vite 前端镜像。
2. 写 Kubernetes base manifests。
3. 接入 Postgres/Redis secrets。
4. 部署到本地 kind 或 minikube。
5. 部署到 GKE/EKS staging。
6. 加 Ingress/TLS。
7. 加 HPA 和资源限制。
8. 加 CI/CD 自动部署。

## 9. 当前验证补充

仓库现在包含 `frontend/` 浏览器运行时，`Dockerfile.frontend` 使用 Node/Vite
构建并由 nginx 提供静态资源，`docker-compose.yml` 作为本地全栈镜像构建路径。
frontend nginx 配置会把 `/api`、`/healthz`、`/readyz`、`/metrics` 代理到
backend service，让浏览器手测保持同源请求。Compose smoke test 需要检查
`http://localhost:8080` 的 UI 和
`http://localhost:8000/healthz` 的 API。
