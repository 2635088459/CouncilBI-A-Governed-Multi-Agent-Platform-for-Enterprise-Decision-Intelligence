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

    assert "DATABASE_URL: postgresql://chatbi:chatbi_password@postgres:5432/chatbi" in text
    assert (
        "CHATBI_READONLY_DATABASE_URL: "
        "postgresql://chatbi_readonly:chatbi_readonly_password@postgres:5432/chatbi"
    ) in text
    assert "REDIS_URL: redis://redis:6379/0" in text
    assert "VECTOR_STORE_URL: memory://local-vector-store" in text
    assert 'CHATBI_USE_POSTGRES_METADATA: "1"' in text
    assert "uvicorn chatbi.api.http:app --host 0.0.0.0 --port 8000" in text


def test_frontend_exposes_only_backend_api_url() -> None:
    text = compose_text()
    frontend_block = service_block(text, "frontend")

    assert "API_BASE_URL: http://backend:8000" in frontend_block
    assert "BACKEND_API_URL: http://backend:8000" in frontend_block
    assert "FRONTEND_ENVIRONMENT: dev" in frontend_block
    assert "FRONTEND_LOCALE_DEFAULT: en" in frontend_block
    assert "DATABASE_URL" not in frontend_block
    assert "REDIS_URL" not in frontend_block
    assert "VECTOR_STORE_URL" not in frontend_block


def test_postgres_and_redis_define_healthchecks() -> None:
    text = compose_text()

    assert "pg_isready -U chatbi -d chatbi" in text
    assert "redis-cli" in text
    assert "ping" in text
    assert "./docker/postgres/init:/docker-entrypoint-initdb.d:ro" in text


def test_backend_and_worker_wait_for_stateful_dependencies() -> None:
    text = compose_text()
    backend_block = service_block(text, "backend")
    worker_block = service_block(text, "worker")

    for block in (backend_block, worker_block):
        assert "postgres:" in block
        assert "redis:" in block
        assert "condition: service_healthy" in block
