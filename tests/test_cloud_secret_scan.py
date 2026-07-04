from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]

DEPLOYMENT_ARTIFACTS = (
    ".github/workflows/fv07-cloud-deployment.yml",
    ".dockerignore",
    "Dockerfile.backend",
    "Dockerfile.worker",
    "Dockerfile.frontend",
    "docker-compose.yml",
    "docker/postgres/init/01-readonly-role.sh",
    "docs/deployment/cloud-kubernetes-runbook.md",
    "k8s/chatbi-runtime.yaml",
    "verification/11-cloud-kubernetes-deployment-verification.md",
)

FORBIDDEN_LITERAL_FRAGMENTS = (
    "chatbi_password",
    "chatbi_readonly_password",
    "super_secret",
    "super-secret",
    "correct horse battery staple",
)

PROVIDER_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
PLAINTEXT_DATABASE_URL_PATTERN = re.compile(r"postgres(?:ql)?://[^:\s]+:[^$:{\s][^@\s]+@")


def test_cloud_deployment_artifacts_do_not_commit_plaintext_secrets() -> None:
    for relative_path in DEPLOYMENT_ARTIFACTS:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for fragment in FORBIDDEN_LITERAL_FRAGMENTS:
            assert fragment not in text, f"{relative_path} contains {fragment}"
        assert PROVIDER_KEY_PATTERN.search(text) is None, relative_path
        assert PLAINTEXT_DATABASE_URL_PATTERN.search(text) is None, relative_path


def test_cloud_deployment_artifacts_use_secret_references_or_placeholders() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    manifest = (REPO_ROOT / "k8s" / "chatbi-runtime.yaml").read_text(encoding="utf-8")
    runbook = (REPO_ROOT / "docs" / "deployment" / "cloud-kubernetes-runbook.md").read_text(
        encoding="utf-8"
    )

    assert "${DATABASE_URL:?DATABASE_URL is required}" in compose
    assert "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}" in compose
    assert "secretKeyRef:" in manifest
    assert "name: chatbi-runtime-secrets" in manifest
    assert "--from-literal=DATABASE_URL=\"$DATABASE_URL\"" in runbook
