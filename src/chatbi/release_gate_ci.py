"""CI step plan for the spec-10 release gate.

`ReleaseGateRunner` decides whether checks pass. This file models the command
order CI should use before it calls that runner: pyright first, pytest second,
evaluation third, and human acceptance last.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.release_gate import ReleaseGateCheckName


@dataclass(frozen=True, slots=True)
class ReleaseGateCiStep:
    name: ReleaseGateCheckName
    command: tuple[str, ...]
    required_before: tuple[ReleaseGateCheckName, ...] = ()

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command is required")
        if any(not part.strip() for part in self.command):
            raise ValueError("command parts must be non-empty")


@dataclass(frozen=True, slots=True)
class ReleaseGateCiPlan:
    steps: tuple[ReleaseGateCiStep, ...]

    @property
    def step_names(self) -> tuple[ReleaseGateCheckName, ...]:
        return tuple(step.name for step in self.steps)

    @property
    def commands(self) -> tuple[tuple[str, ...], ...]:
        return tuple(step.command for step in self.steps)


def default_release_gate_ci_plan() -> ReleaseGateCiPlan:
    """Return the project-local CI order required by spec 10."""

    return ReleaseGateCiPlan(
        steps=(
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.PYRIGHT,
                command=(".venv313/bin/python", "-m", "pyright", "src", "tests"),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.PYTEST,
                command=(".venv313/bin/python", "-m", "pytest"),
                required_before=(ReleaseGateCheckName.PYRIGHT,),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.EVALUATION,
                command=(
                    ".venv313/bin/python",
                    "-m",
                    "pytest",
                    "tests/test_evaluation_repository.py",
                    "tests/test_release_gate.py",
                ),
                required_before=(ReleaseGateCheckName.PYRIGHT, ReleaseGateCheckName.PYTEST),
            ),
            ReleaseGateCiStep(
                name=ReleaseGateCheckName.HUMAN_ACCEPTANCE,
                command=("manual-review", "spec/version2/10-evaluation-and-observability.spec.md"),
                required_before=(
                    ReleaseGateCheckName.PYRIGHT,
                    ReleaseGateCheckName.PYTEST,
                    ReleaseGateCheckName.EVALUATION,
                ),
            ),
        )
    )


def validate_release_gate_ci_order(plan: ReleaseGateCiPlan) -> None:
    """Raise when a CI plan violates the spec-required gate order."""

    seen: set[ReleaseGateCheckName] = set()
    for step in plan.steps:
        missing_prerequisites = tuple(
            prerequisite
            for prerequisite in step.required_before
            if prerequisite not in seen
        )
        if missing_prerequisites:
            missing_text = ", ".join(name.value for name in missing_prerequisites)
            raise ValueError(
                f"{step.name.value} must run after required step(s): {missing_text}"
            )
        seen.add(step.name)

    _require_step_order(
        plan=plan,
        earlier=ReleaseGateCheckName.PYRIGHT,
        later=ReleaseGateCheckName.PYTEST,
    )
    _require_step_order(
        plan=plan,
        earlier=ReleaseGateCheckName.PYTEST,
        later=ReleaseGateCheckName.EVALUATION,
    )
    _require_step_order(
        plan=plan,
        earlier=ReleaseGateCheckName.EVALUATION,
        later=ReleaseGateCheckName.HUMAN_ACCEPTANCE,
    )


def _require_step_order(
    plan: ReleaseGateCiPlan,
    earlier: ReleaseGateCheckName,
    later: ReleaseGateCheckName,
) -> None:
    names = plan.step_names
    if earlier not in names:
        raise ValueError(f"{earlier.value} step is required")
    if later not in names:
        raise ValueError(f"{later.value} step is required")
    if names.index(earlier) > names.index(later):
        raise ValueError(f"{earlier.value} must run before {later.value}")
