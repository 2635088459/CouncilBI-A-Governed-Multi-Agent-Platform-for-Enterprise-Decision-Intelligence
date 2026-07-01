from pathlib import Path


WORKFLOW = Path(".github/workflows/spec-10-release-gate.yml")


def test_spec10_release_gate_workflow_runs_pyright_before_pytest_and_evaluation() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    pyright_index = workflow_text.index("- name: Pyright gate")
    pytest_index = workflow_text.index("- name: Pytest gate")
    evaluation_index = workflow_text.index("- name: Evaluation gate")
    human_acceptance_index = workflow_text.index("- name: Human acceptance checklist")

    assert pyright_index < pytest_index < evaluation_index < human_acceptance_index


def test_spec10_release_gate_workflow_points_to_spec_and_verification_docs() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert "spec/version2/10-evaluation-and-observability.spec.md" in workflow_text
    assert "verification/10-evaluation-and-observability-verification.md" in workflow_text
    assert "tests/test_release_gate_ci.py" in workflow_text
