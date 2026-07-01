from chatbi.release_gate import (
    ReleaseGateCheckResult,
    ReleaseGateCheckName,
    ReleaseGateRunner,
    evaluation_sql_safety_check,
    failed_check,
    passed_check,
)


def test_release_gate_runs_pyright_before_pytest_and_evaluation() -> None:
    calls: list[str] = []

    report = ReleaseGateRunner(
        pyright_check=lambda: _record(calls, passed_check(ReleaseGateCheckName.PYRIGHT)),
        pytest_check=lambda: _record(calls, passed_check(ReleaseGateCheckName.PYTEST)),
        evaluation_check=lambda: _record(calls, evaluation_sql_safety_check(1.0)),
        human_acceptance_check=lambda: _record(
            calls,
            passed_check(ReleaseGateCheckName.HUMAN_ACCEPTANCE),
        ),
    ).run()

    assert calls == ["pyright", "pytest", "evaluation", "human_acceptance"]
    assert report.release_allowed is True
    assert report.execution_order == (
        "pyright",
        "pytest",
        "evaluation",
        "human_acceptance",
    )


def test_release_gate_stops_after_pyright_failure() -> None:
    calls: list[str] = []

    report = ReleaseGateRunner(
        pyright_check=lambda: _record(
            calls,
            failed_check(ReleaseGateCheckName.PYRIGHT, "pyright reported errors."),
        ),
        pytest_check=lambda: _record(calls, passed_check(ReleaseGateCheckName.PYTEST)),
        evaluation_check=lambda: _record(calls, evaluation_sql_safety_check(1.0)),
        human_acceptance_check=lambda: _record(
            calls,
            passed_check(ReleaseGateCheckName.HUMAN_ACCEPTANCE),
        ),
    ).run()

    assert calls == ["pyright"]
    assert report.release_allowed is False
    assert report.failed_check is not None
    assert report.failed_check.name is ReleaseGateCheckName.PYRIGHT
    assert report.execution_order == (
        "pyright",
        "pytest",
        "evaluation",
        "human_acceptance",
    )
    assert report.checks[1].status == "skipped"
    assert report.checks[3].message == "Skipped because machine gates failed."


def test_release_gate_stops_after_pytest_failure() -> None:
    calls: list[str] = []

    report = ReleaseGateRunner(
        pyright_check=lambda: _record(calls, passed_check(ReleaseGateCheckName.PYRIGHT)),
        pytest_check=lambda: _record(
            calls,
            failed_check(ReleaseGateCheckName.PYTEST, "pytest failed."),
        ),
        evaluation_check=lambda: _record(calls, evaluation_sql_safety_check(1.0)),
        human_acceptance_check=lambda: _record(
            calls,
            passed_check(ReleaseGateCheckName.HUMAN_ACCEPTANCE),
        ),
    ).run()

    assert calls == ["pyright", "pytest"]
    assert report.release_allowed is False
    assert report.failed_check is not None
    assert report.failed_check.name is ReleaseGateCheckName.PYTEST
    assert report.execution_order == (
        "pyright",
        "pytest",
        "evaluation",
        "human_acceptance",
    )
    assert report.checks[2].status == "skipped"


def test_release_gate_blocks_sql_safety_below_one_hundred_percent() -> None:
    report = ReleaseGateRunner(
        pyright_check=lambda: passed_check(ReleaseGateCheckName.PYRIGHT),
        pytest_check=lambda: passed_check(ReleaseGateCheckName.PYTEST),
        evaluation_check=lambda: evaluation_sql_safety_check(0.99),
        human_acceptance_check=lambda: passed_check(ReleaseGateCheckName.HUMAN_ACCEPTANCE),
    ).run()

    assert report.release_allowed is False
    assert report.failed_check is not None
    assert report.failed_check.name is ReleaseGateCheckName.EVALUATION
    assert "SQL safety score must be 1.0" in report.failed_check.message
    assert report.checks[-1].name is ReleaseGateCheckName.HUMAN_ACCEPTANCE
    assert report.checks[-1].status == "skipped"


def test_human_acceptance_cannot_override_machine_gate_failure() -> None:
    report = ReleaseGateRunner(
        pyright_check=lambda: passed_check(ReleaseGateCheckName.PYRIGHT),
        pytest_check=lambda: failed_check(ReleaseGateCheckName.PYTEST, "pytest failed."),
        evaluation_check=lambda: evaluation_sql_safety_check(1.0),
        human_acceptance_check=lambda: passed_check(
            ReleaseGateCheckName.HUMAN_ACCEPTANCE,
            "Looks good to a reviewer.",
        ),
    ).run()

    assert report.release_allowed is False
    assert report.execution_order == (
        "pyright",
        "pytest",
        "evaluation",
        "human_acceptance",
    )
    assert report.checks[-1].status == "skipped"


def _record(
    calls: list[str],
    result: ReleaseGateCheckResult,
) -> ReleaseGateCheckResult:
    calls.append(result.name.value)
    return result
