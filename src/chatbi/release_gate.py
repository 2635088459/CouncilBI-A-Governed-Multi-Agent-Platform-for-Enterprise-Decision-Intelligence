"""Release gate process for spec 10.

This module models the CI order, not the shell commands themselves. Real CI can
plug in pyright, pytest, evaluation, and human-acceptance command wrappers. The
important rule is the order: pyright must pass before pytest, pytest must pass
before evaluation, and human acceptance can never override a failed machine
gate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class ReleaseGateCheckName(StrEnum):
    PYRIGHT = "pyright"
    PYTEST = "pytest"
    EVALUATION = "evaluation"
    HUMAN_ACCEPTANCE = "human_acceptance"


class ReleaseGateCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ReleaseGateCheckResult:
    name: ReleaseGateCheckName
    status: ReleaseGateCheckStatus
    message: str = ""

    @property
    def passed(self) -> bool:
        return self.status is ReleaseGateCheckStatus.PASSED


@dataclass(frozen=True, slots=True)
class ReleaseGateReport:
    checks: tuple[ReleaseGateCheckResult, ...]

    @property
    def release_allowed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_check(self) -> ReleaseGateCheckResult | None:
        for check in self.checks:
            if check.status is ReleaseGateCheckStatus.FAILED:
                return check
        return None

    @property
    def execution_order(self) -> tuple[str, ...]:
        return tuple(check.name.value for check in self.checks)


MachineCheck = Callable[[], ReleaseGateCheckResult]


class ReleaseGateRunner:
    """Run release checks in the spec-required order."""

    def __init__(
        self,
        pyright_check: MachineCheck,
        pytest_check: MachineCheck,
        evaluation_check: MachineCheck,
        human_acceptance_check: MachineCheck | None = None,
    ) -> None:
        self._pyright_check = pyright_check
        self._pytest_check = pytest_check
        self._evaluation_check = evaluation_check
        self._human_acceptance_check = human_acceptance_check

    def run(self) -> ReleaseGateReport:
        checks: list[ReleaseGateCheckResult] = []

        pyright_result = self._run_named_check(
            expected_name=ReleaseGateCheckName.PYRIGHT,
            check=self._pyright_check,
        )
        checks.append(pyright_result)
        if not pyright_result.passed:
            checks.extend(self._skipped_after_pyright())
            return ReleaseGateReport(checks=tuple(checks))

        pytest_result = self._run_named_check(
            expected_name=ReleaseGateCheckName.PYTEST,
            check=self._pytest_check,
        )
        checks.append(pytest_result)
        if not pytest_result.passed:
            checks.extend(self._skipped_after_pytest())
            return ReleaseGateReport(checks=tuple(checks))

        evaluation_result = self._run_named_check(
            expected_name=ReleaseGateCheckName.EVALUATION,
            check=self._evaluation_check,
        )
        checks.append(evaluation_result)
        if not evaluation_result.passed:
            checks.extend(self._skipped_human_acceptance())
            return ReleaseGateReport(checks=tuple(checks))

        if self._human_acceptance_check is not None:
            checks.append(
                self._run_named_check(
                    expected_name=ReleaseGateCheckName.HUMAN_ACCEPTANCE,
                    check=self._human_acceptance_check,
                )
            )
        return ReleaseGateReport(checks=tuple(checks))

    def _run_named_check(
        self,
        expected_name: ReleaseGateCheckName,
        check: MachineCheck,
    ) -> ReleaseGateCheckResult:
        result = check()
        if result.name is not expected_name:
            raise ValueError(f"release gate expected {expected_name.value} check")
        return result

    def _skipped_after_pyright(self) -> tuple[ReleaseGateCheckResult, ...]:
        return (
            skipped_check(ReleaseGateCheckName.PYTEST, "Skipped because pyright failed."),
            skipped_check(ReleaseGateCheckName.EVALUATION, "Skipped because pyright failed."),
            skipped_check(
                ReleaseGateCheckName.HUMAN_ACCEPTANCE,
                "Skipped because machine gates failed.",
            ),
        )

    def _skipped_after_pytest(self) -> tuple[ReleaseGateCheckResult, ...]:
        return (
            skipped_check(ReleaseGateCheckName.EVALUATION, "Skipped because pytest failed."),
            skipped_check(
                ReleaseGateCheckName.HUMAN_ACCEPTANCE,
                "Skipped because machine gates failed.",
            ),
        )

    def _skipped_human_acceptance(self) -> tuple[ReleaseGateCheckResult, ...]:
        return (
            skipped_check(
                ReleaseGateCheckName.HUMAN_ACCEPTANCE,
                "Skipped because machine gates failed.",
            ),
        )


def passed_check(name: ReleaseGateCheckName, message: str = "") -> ReleaseGateCheckResult:
    return ReleaseGateCheckResult(
        name=name,
        status=ReleaseGateCheckStatus.PASSED,
        message=message,
    )


def failed_check(name: ReleaseGateCheckName, message: str) -> ReleaseGateCheckResult:
    return ReleaseGateCheckResult(
        name=name,
        status=ReleaseGateCheckStatus.FAILED,
        message=message,
    )


def skipped_check(name: ReleaseGateCheckName, message: str) -> ReleaseGateCheckResult:
    return ReleaseGateCheckResult(
        name=name,
        status=ReleaseGateCheckStatus.SKIPPED,
        message=message,
    )


def evaluation_sql_safety_check(sql_safety_score: float) -> ReleaseGateCheckResult:
    if sql_safety_score == 1.0:
        return passed_check(
            ReleaseGateCheckName.EVALUATION,
            "SQL safety score is 100%.",
        )
    return failed_check(
        ReleaseGateCheckName.EVALUATION,
        f"SQL safety score must be 1.0 but was {sql_safety_score}.",
    )
