from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def dockerfile_text(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def test_backend_dockerfile_builds_api_image_from_source() -> None:
    text = dockerfile_text("Dockerfile.backend")

    assert "FROM python:3.12-slim" in text
    assert "COPY src ./src" in text
    assert "pip install --no-cache-dir ." in text
    assert 'CMD ["uvicorn", "chatbi.api.http:app"' in text
    assert "EXPOSE 8000" in text


def test_worker_dockerfile_builds_worker_image_from_source() -> None:
    text = dockerfile_text("Dockerfile.worker")

    assert "FROM python:3.12-slim" in text
    assert "COPY src ./src" in text
    assert "pip install --no-cache-dir ." in text
    assert "chatbi worker ready" in text


def test_frontend_dockerfile_builds_static_assets_and_serves_with_nginx() -> None:
    text = dockerfile_text("Dockerfile.frontend")

    assert "FROM node:20-alpine AS builder" in text
    assert "COPY frontend/package.json ./package.json" in text
    assert "npm install" in text
    assert "ARG VITE_API_BASE_URL=" in text
    assert "npm run build" in text
    assert "FROM nginx:1.27-alpine AS runtime" in text
    assert "COPY --from=builder /app/dist /usr/share/nginx/html" in text
    assert "COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf" in text
    assert "EXPOSE 80" in text


def test_dockerignore_excludes_local_state_and_virtualenvs() -> None:
    text = dockerfile_text(".dockerignore")

    for ignored_path in (
        ".git",
        ".venv",
        ".venv313",
        ".pytest_cache",
        "dist",
        "frontend/node_modules",
        "frontend/dist",
    ):
        assert ignored_path in text
