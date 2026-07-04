from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def compose_text() -> str:
    return COMPOSE_FILE.read_text(encoding="utf-8")


def service_block(text: str, service_name: str) -> str:
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line == f"  {service_name}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            end = index
            break
    return "\n".join(lines[start:end])


def test_docker_compose_defines_required_runtime_services() -> None:
    text = compose_text()

    for service_name in ("frontend", "backend", "postgres", "redis", "worker"):
        assert f"  {service_name}:" in text


def test_backend_runtime_is_wired_to_postgres_redis_and_vector_store() -> None:
    text = compose_text()
    backend_block = service_block(text, "backend")
    worker_block = service_block(text, "worker")

    assert "DATABASE_URL: ${DATABASE_URL:?DATABASE_URL is required}" in text
    assert (
        "CHATBI_READONLY_DATABASE_URL: "
        "${CHATBI_READONLY_DATABASE_URL:?CHATBI_READONLY_DATABASE_URL is required}"
    ) in text
    assert "REDIS_URL: redis://redis:6379/0" in text
    assert "VECTOR_STORE_URL: memory://local-vector-store" in text
    assert 'CHATBI_USE_POSTGRES_METADATA: "1"' in text
    assert "CHATBI_LLM_PROVIDER: ${CHATBI_LLM_PROVIDER:-mock}" in backend_block
    assert "CHATBI_LLM_MODEL: ${CHATBI_LLM_MODEL:-}" in backend_block
    assert "OPENAI_API_KEY: ${OPENAI_API_KEY:-}" in backend_block
    assert "OPENAI_BASE_URL: ${OPENAI_BASE_URL:-}" in backend_block
    assert "CHATBI_LLM_PROVIDER: ${CHATBI_LLM_PROVIDER:-mock}" in worker_block
    assert "OPENAI_API_KEY: ${OPENAI_API_KEY:-}" in worker_block
    assert "dockerfile: Dockerfile.backend" in backend_block
    assert "image: governed-chatbi-backend:local" in backend_block
    assert "dockerfile: Dockerfile.worker" in worker_block
    assert "image: governed-chatbi-worker:local" in worker_block


def test_frontend_builds_react_vite_image_and_exposes_only_browser_api_url() -> None:
    text = compose_text()
    frontend_block = service_block(text, "frontend")

    assert "dockerfile: Dockerfile.frontend" in frontend_block
    assert "image: governed-chatbi-frontend:local" in frontend_block
    assert "VITE_API_BASE_URL:" not in frontend_block
    assert "cat >/usr/share/nginx/html/index.html" not in frontend_block
    assert "\n      API_BASE_URL:" not in frontend_block
    assert "BACKEND_API_URL:" not in frontend_block
    assert "FRONTEND_ENVIRONMENT:" not in frontend_block
    assert "FRONTEND_LOCALE_DEFAULT:" not in frontend_block
    assert "DATABASE_URL" not in frontend_block
    assert "REDIS_URL" not in frontend_block
    assert "VECTOR_STORE_URL" not in frontend_block


def test_frontend_nginx_proxies_api_to_backend_for_same_origin_ui() -> None:
    nginx = (REPO_ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")

    assert "location /api/" in nginx
    assert "proxy_pass http://backend:8000/api/" in nginx
    assert "location = /healthz" in nginx
    assert "proxy_pass http://backend:8000/healthz" in nginx
    assert "try_files $uri /index.html" in nginx


def test_postgres_and_redis_define_healthchecks() -> None:
    text = compose_text()

    assert "pg_isready -U chatbi -d chatbi" in text
    assert "redis-cli" in text
    assert "ping" in text
    assert "./docker/postgres/init:/docker-entrypoint-initdb.d:ro" in text
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}" in text
    assert (
        "CHATBI_READONLY_PASSWORD: "
        "${CHATBI_READONLY_PASSWORD:?CHATBI_READONLY_PASSWORD is required}"
    ) in text


def test_backend_and_worker_wait_for_stateful_dependencies() -> None:
    text = compose_text()
    backend_block = service_block(text, "backend")
    worker_block = service_block(text, "worker")

    for block in (backend_block, worker_block):
        assert "postgres:" in block
        assert "redis:" in block
        assert "condition: service_healthy" in block
