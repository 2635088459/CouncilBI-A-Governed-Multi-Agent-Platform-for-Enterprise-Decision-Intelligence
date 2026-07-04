from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
K8S_FILE = REPO_ROOT / "k8s" / "chatbi-runtime.yaml"


def manifest_text() -> str:
    return K8S_FILE.read_text(encoding="utf-8")


def document_for_resource(text: str, kind: str, name: str) -> str:
    documents = text.split("---")
    for document in documents:
        if f"kind: {kind}" in document and f"  name: {name}" in document:
            return document
    raise AssertionError(f"manifest document for {kind}/{name} was not found")


def test_k8s_manifest_defines_required_workloads() -> None:
    text = manifest_text()

    for workload_name in ("backend", "frontend", "worker", "redis", "postgres"):
        document_for_resource(text, "Deployment", workload_name)


def test_k8s_manifest_defines_backend_and_frontend_services() -> None:
    text = manifest_text()

    for service_name in ("backend", "frontend", "redis", "postgres"):
        document_for_resource(text, "Service", service_name)


def test_k8s_ingress_routes_api_to_backend_and_root_to_frontend() -> None:
    ingress = document_for_resource(manifest_text(), "Ingress", "chatbi-web")
    lines = ingress.splitlines()

    api_path_index = lines.index("          - path: /api")
    root_path_index = lines.index("          - path: /")

    assert api_path_index < root_path_index
    assert "pathType: Prefix" in ingress
    assert "name: backend" in ingress
    assert "number: 8000" in ingress
    assert "name: frontend" in ingress
    assert "number: 80" in ingress


def test_backend_deployment_uses_runtime_dependency_environment() -> None:
    backend = document_for_resource(manifest_text(), "Deployment", "backend")

    assert "name: DATABASE_URL" in backend
    assert "key: DATABASE_URL" in backend
    assert "name: REDIS_URL" in backend
    assert "key: REDIS_URL" in backend
    assert "name: VECTOR_STORE_URL" in backend
    assert "key: VECTOR_STORE_URL" in backend
    assert "name: CHATBI_USE_POSTGRES_METADATA" in backend
    assert "key: CHATBI_USE_POSTGRES_METADATA" in backend
    assert "path: /readyz" in backend
    assert "path: /healthz" in backend


def test_backend_and_worker_read_database_url_from_secret_reference() -> None:
    text = manifest_text()

    for workload_name in ("backend", "worker"):
        workload = document_for_resource(text, "Deployment", workload_name)
        assert "name: DATABASE_URL" in workload
        assert "secretKeyRef:" in workload
        assert "name: chatbi-runtime-secrets" in workload
        assert "key: DATABASE_URL" in workload


def test_frontend_deployment_exposes_only_backend_api_url() -> None:
    frontend = document_for_resource(manifest_text(), "Deployment", "frontend")

    assert "name: API_BASE_URL" in frontend
    assert "key: API_BASE_URL" in frontend
    assert "name: FRONTEND_ENVIRONMENT" in frontend
    assert "key: FRONTEND_ENVIRONMENT" in frontend
    assert "name: FRONTEND_LOCALE_DEFAULT" in frontend
    assert "key: FRONTEND_LOCALE_DEFAULT" in frontend
    assert "name: BACKEND_API_URL" in frontend
    assert "DATABASE_URL" not in frontend
    assert "REDIS_URL" not in frontend
    assert "VECTOR_STORE_URL" not in frontend


def test_worker_deployment_receives_stateful_dependency_environment() -> None:
    worker = document_for_resource(manifest_text(), "Deployment", "worker")

    assert "name: DATABASE_URL" in worker
    assert "name: REDIS_URL" in worker
    assert "name: VECTOR_STORE_URL" in worker
    assert "name: CHATBI_USE_POSTGRES_METADATA" in worker


def test_redis_and_postgres_have_readiness_checks() -> None:
    redis = document_for_resource(manifest_text(), "Deployment", "redis")
    postgres = document_for_resource(manifest_text(), "Deployment", "postgres")

    assert "redis-cli" in redis
    assert "ping" in redis
    assert "pg_isready" in postgres


def test_deployments_define_resource_requests_and_limits() -> None:
    text = manifest_text()

    for workload_name in ("backend", "frontend", "worker", "redis", "postgres"):
        workload = document_for_resource(text, "Deployment", workload_name)
        assert "resources:" in workload
        assert "requests:" in workload
        assert "limits:" in workload
        assert "cpu:" in workload
        assert "memory:" in workload


def test_backend_hpa_exists_for_api_scaling_policy() -> None:
    hpa = document_for_resource(manifest_text(), "HorizontalPodAutoscaler", "backend")

    assert "kind: Deployment" in hpa
    assert "name: backend" in hpa
    assert "minReplicas: 2" in hpa
    assert "maxReplicas: 6" in hpa
    assert "averageUtilization: 70" in hpa


def test_k8s_manifest_does_not_commit_plaintext_provider_or_database_secrets() -> None:
    text = manifest_text()

    forbidden_fragments = (
        "chatbi_password",
        "chatbi_readonly_password",
        "postgresql://chatbi:",
        "OPENAI_API_KEY:",
        "sk-",
        "api_key:",
        "password:",
        "token:",
    )
    for fragment in forbidden_fragments:
        assert fragment not in text
