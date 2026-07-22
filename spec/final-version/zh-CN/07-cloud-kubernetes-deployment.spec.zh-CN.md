11# Spec FV-07：云端与 Kubernetes 部署

来源设计：
- [云端与 Kubernetes 设计](../../../system_design/final-version/zh-CN/06-cloud-kubernetes-deployment.zh-CN.md)
- [最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)

## 1. 目的
定义 Docker、Kubernetes、云端配置、CI/CD 和 smoke test 要求，让项目具备 staging 和 production 部署准备度。

## 2. 范围
范围内：
- Docker image build、Kubernetes manifests 或 Helm chart、ingress、health checks、secrets、resource limits、HPA。
- staging deployment、smoke tests、CI/CD gates、rollback readiness。

范围外：
- 完整多云抽象。
- 深度生产成本优化。

## 3. 功能需求
| ID | 需求 |
|---|---|
| FR-FV07-001 | backend、worker、frontend images 必须能从源码构建。 |
| FR-FV07-002 | Kubernetes manifests 必须定义 deployments、services、config、secret references、ingress。 |
| FR-FV07-003 | runtime services 必须暴露 liveness 和 readiness probes。 |
| FR-FV07-004 | secrets 必须由 Kubernetes Secret 或 cloud secret manager 提供，不能提交明文文件。 |
| FR-FV07-005 | deployments 必须定义 resource requests 和 limits。 |
| FR-FV07-006 | staging environment 必须支持 managed PostgreSQL/Redis 配置。 |
| FR-FV07-007 | CI/CD 必须运行 tests、build images、release gate、deploy staging、smoke tests。 |
| FR-FV07-008 | release process 必须支持 rollback 或重新部署前一个 image。 |

## 4. 非功能需求
| ID | 需求 |
|---|---|
| NFR-FV07-001 | staging smoke test 中 health endpoints P99 应 <= 200ms。 |
| NFR-FV07-002 | manifests 不能包含明文 API key、password、token。 |
| NFR-FV07-003 | staging deploy 应能通过文档命令复现。 |
| NFR-FV07-004 | 生产提交前 API service 必须有 HPA 或 scaling policy。 |

## 5. 验收标准
| ID | 标准 |
|---|---|
| AC-FV07-001 | Docker images 在 CI 中构建成功。 |
| AC-FV07-002 | Kubernetes manifests 通过验证并部署到 staging。 |
| AC-FV07-003 | staging `/healthz` 和 `/readyz` smoke tests 通过。 |
| AC-FV07-004 | secret scan 确认没有提交 provider key 或 database password。 |
| AC-FV07-005 | resource limits、probes、ingress、HPA/scaling config 存在。 |

## 6. 测试计划
| ID | 层级 | 描述 |
|---|---|---|
| TC-FV07-001 | build | 构建 backend、worker、frontend Docker images。 |
| TC-FV07-002 | static | 校验 Kubernetes YAML schema 和 required fields。 |
| TC-FV07-003 | security | secret scanning 拒绝提交 secrets。 |
| TC-FV07-004 | deploy | 部署 manifests 到 local cluster 或 staging namespace。 |
| TC-FV07-005 | smoke | 调用 `/healthz`、`/readyz` 和一个 authenticated API path。 |
| TC-FV07-006 | config | 验证 staging 能连接配置的 PostgreSQL 和 Redis。 |
| TC-FV07-007 | release | rollback procedure 有文档，并至少 smoke-tested 一次。 |

已实现测试覆盖：
- `tests/test_cloud_deployment_workflow.py`
- `tests/test_cloud_deployment_runbook.py`
- `tests/test_cloud_secret_scan.py`
- `tests/test_dockerfiles.py`
- `tests/test_docker_compose_architecture.py`
- `tests/test_k8s_runtime_architecture.py`

已实现部署产物：
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

已实现证据：
- `FR-FV07-001`：backend、worker、frontend Dockerfiles 均从 repository source 构建；frontend image 使用 `chatbi-build-frontend` 生成静态资源，并由 nginx 提供服务。
- `FR-FV07-002`：manifest 定义 backend、frontend、worker、Redis、PostgreSQL、services、config maps、secret references 和 ingress routes。
- `FR-FV07-003`：backend 暴露 `/healthz` liveness 和 `/readyz` readiness probes；Redis 和 PostgreSQL 暴露依赖 readiness probes。
- `FR-FV07-004` / `NFR-FV07-002`：数据库凭据通过 `secretKeyRef`（`chatbi-runtime-secrets`）或 required environment placeholders 引用。`tests/test_cloud_secret_scan.py` 会拒绝 deployment artifacts 中提交的 provider keys、database passwords、plaintext database URLs 和 token fragments。
- `FR-FV07-005` / `NFR-FV07-004`：Deployments 定义 resource requests/limits，并且 backend API 有 `HorizontalPodAutoscaler`。
- `FR-FV07-006`：`chatbi-managed-service-config` 和 `chatbi-runtime-secrets` 支持 managed PostgreSQL/Redis staging endpoints，并且不提交凭据。
- `FR-FV07-007`：`.github/workflows/fv07-cloud-deployment.yml` 运行 type checks、deployment tests、Docker image builds、release-gate tests、可选 staging deployment 和 smoke tests。
- `FR-FV07-008`：staging workflow 和 runbook 文档化 backend、frontend 和 worker 的 `kubectl rollout undo` 命令。
- `NFR-FV07-001`：staging smoke commands 会调用 `/healthz` 和 `/readyz`；本地 P99 覆盖由 `tests/test_runtime_latency_smoke.py` 提供。
- `NFR-FV07-003`：`docs/deployment/cloud-kubernetes-runbook.md` 文档化可复现的 build、secret creation、deploy、smoke 和 rollback commands。

## 7. 追踪矩阵
| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV07-001 | AC-FV07-001 | TC-FV07-001 |
| FR-FV07-002 | AC-FV07-002 | TC-FV07-002, TC-FV07-004 |
| FR-FV07-003 | AC-FV07-003 | TC-FV07-005 |
| FR-FV07-004 | AC-FV07-004 | TC-FV07-003 |
| FR-FV07-005 | AC-FV07-005 | TC-FV07-002 |
| FR-FV07-006 | AC-FV07-003 | TC-FV07-006 |
| FR-FV07-007 | AC-FV07-001 | TC-FV07-001, TC-FV07-005 |
| FR-FV07-008 | AC-FV07-005 | TC-FV07-007 |
