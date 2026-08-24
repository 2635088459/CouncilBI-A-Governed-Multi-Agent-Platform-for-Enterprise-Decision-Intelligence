from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "fv07-cloud-deployment.yml"


def workflow_text() -> str:
    return WORKFLOW_FILE.read_text(encoding="utf-8")


def test_cloud_deployment_workflow_runs_tests_builds_images_and_release_gate() -> None:
    text = workflow_text()

    assert "python -m pyright" in text
    assert "python -m pytest" in text
    assert "docker build -f Dockerfile.backend" in text
    assert "docker build -f Dockerfile.worker" in text
    assert "docker build -f Dockerfile.frontend" in text
    assert "tests/test_release_gate.py" in text
    assert "tests/test_release_gate_ci.py" in text


def test_cloud_deployment_workflow_deploys_staging_and_smokes_health_endpoints() -> None:
    text = workflow_text()

    assert "kubectl apply -f k8s/chatbi-runtime.yaml" in text
    assert "kubectl rollout status deployment/backend -n chatbi" in text
    assert "$STAGING_BASE_URL/healthz" in text
    assert "$STAGING_BASE_URL/readyz" in text
    assert "$STAGING_BASE_URL/api/v2/chat/query" in text
    assert "req_staging_smoke" in text


def test_cloud_deployment_workflow_uses_secrets_not_plaintext_credentials() -> None:
    text = workflow_text()

    assert "secrets.STAGING_KUBE_CONFIG_B64" in text
    assert "secrets.STAGING_AUTH_TOKEN" in text
    forbidden_fragments = ("chatbi_password", "sk-", "api_key:", "password:", "token:")
    for fragment in forbidden_fragments:
        assert fragment not in text


def test_cloud_deployment_workflow_contains_rollback_commands() -> None:
    text = workflow_text()

    assert "kubectl rollout undo deployment/backend -n chatbi" in text
    assert "kubectl rollout undo deployment/frontend -n chatbi" in text
    assert "kubectl rollout undo deployment/worker -n chatbi" in text
