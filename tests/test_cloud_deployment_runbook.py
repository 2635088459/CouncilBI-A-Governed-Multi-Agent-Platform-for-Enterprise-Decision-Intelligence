from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK_FILE = REPO_ROOT / "docs" / "deployment" / "cloud-kubernetes-runbook.md"
VERIFICATION_FILE = REPO_ROOT / "verification" / "11-cloud-kubernetes-deployment-verification.md"


def runbook_text() -> str:
    return RUNBOOK_FILE.read_text(encoding="utf-8")


def verification_text() -> str:
    return VERIFICATION_FILE.read_text(encoding="utf-8")


def test_cloud_runbook_documents_reproducible_build_and_deploy_commands() -> None:
    text = runbook_text()

    assert "docker build -f Dockerfile.backend" in text
    assert "docker build -f Dockerfile.worker" in text
    assert "docker build -f Dockerfile.frontend" in text
    assert "kubectl create secret generic chatbi-runtime-secrets" in text
    assert "kubectl apply -f k8s/chatbi-runtime.yaml" in text
    assert "kubectl rollout status deployment/backend -n chatbi" in text


def test_cloud_runbook_documents_smoke_and_rollback_commands() -> None:
    text = runbook_text()

    assert "$STAGING_BASE_URL/healthz" in text
    assert "$STAGING_BASE_URL/readyz" in text
    assert "$STAGING_BASE_URL/api/v2/me" in text
    assert "python -m pytest tests/test_runtime_latency_smoke.py" in text
    assert "kubectl rollout history deployment/backend -n chatbi" in text
    assert "kubectl rollout undo deployment/backend -n chatbi" in text
    assert "kubectl rollout undo deployment/frontend -n chatbi" in text
    assert "kubectl rollout undo deployment/worker -n chatbi" in text


def test_cloud_runbook_uses_secret_placeholders_not_plaintext_credentials() -> None:
    text = runbook_text()

    assert "--from-literal=DATABASE_URL=\"$DATABASE_URL\"" in text
    assert "--from-literal=POSTGRES_PASSWORD=\"$POSTGRES_PASSWORD\"" in text
    forbidden_fragments = (
        "chatbi_password",
        "chatbi_readonly_password",
        "postgresql://chatbi:",
        "sk-",
        "super-secret",
    )
    for fragment in forbidden_fragments:
        assert fragment not in text


def test_cloud_verification_report_links_fv07_requirements_to_artifacts() -> None:
    text = verification_text()

    for requirement in (
        "FR-FV07-001",
        "FR-FV07-002",
        "FR-FV07-003",
        "FR-FV07-004",
        "FR-FV07-005",
        "FR-FV07-006",
        "FR-FV07-007",
        "FR-FV07-008",
    ):
        assert requirement in text
    assert "tests/test_cloud_deployment_runbook.py" in text
    assert "kubectl rollout undo" in text
