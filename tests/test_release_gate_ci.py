from chatbi.release_gate import ReleaseGateCheckName
from chatbi.release_gate_ci import (
    ReleaseGateCiPlan,
    ReleaseGateCiStep,
    default_release_gate_ci_plan,
    validate_release_gate_ci_order,
)


def test_default_release_gate_ci_plan_runs_pyright_before_pytest() -> None:
    plan = default_release_gate_ci_plan()

    validate_release_gate_ci_order(plan)

    assert plan.step_names == (
        ReleaseGateCheckName.PYRIGHT,
        ReleaseGateCheckName.PYTEST,
        ReleaseGateCheckName.EVALUATION,
        ReleaseGateCheckName.HUMAN_ACCEPTANCE,
    )
    assert plan.commands[0] == (".venv313/bin/python", "-m", "pyright", "src", "tests")
    assert plan.commands[1] == (".venv313/bin/python", "-m", "pytest")


def test_release_gate_ci_plan_rejects_pytest_before_pyright() -> None:
    plan = ReleaseGateCiPlan(
        steps=(
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.PYTEST,
                command=("pytest",),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.PYRIGHT,
                command=("pyright",),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.EVALUATION,
                command=("pytest", "tests/test_release_gate.py"),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.HUMAN_ACCEPTANCE,
                command=("manual-review",),
            ),
        )
    )

    try:
        validate_release_gate_ci_order(plan)
    except ValueError as exc:
        assert "pyright must run before pytest" in str(exc)
    else:
        raise AssertionError("Expected CI order validation to reject pytest before pyright.")


def test_release_gate_ci_plan_rejects_human_acceptance_before_machine_gates() -> None:
    plan = ReleaseGateCiPlan(
        steps=(
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.PYRIGHT,
                command=("pyright",),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.HUMAN_ACCEPTANCE,
                command=("manual-review",),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.PYTEST,
                command=("pytest",),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.EVALUATION,
                command=("pytest", "tests/test_release_gate.py"),
            ),
        )
    )

    try:
        validate_release_gate_ci_order(plan)
    except ValueError as exc:
        assert "evaluation must run before human_acceptance" in str(exc)
    else:
        raise AssertionError(
            "Expected CI order validation to reject human acceptance before evaluation."
        )
