from typing import Any, Mapping

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import EvaluationRunViewModel, FrontendUserContext
from chatbi.frontend.component_props import ComponentId, build_evaluation_page_props
from chatbi.frontend.evaluation_state import EvaluationPageState, ReleaseGateStatus


def test_build_evaluation_page_props_renders_not_run_state() -> None:
    state = EvaluationPageState(
        context=_context(locale=Locale.ZH_CN),
        eval_suite_id="frontend_smoke",
        questions=("显示收入趋势。",),
    )

    props = build_evaluation_page_props(state, Locale.ZH_CN)

    assert props.title == "评估"
    assert props.empty_state == "运行评估套件来查看发布质量。"
    assert props.input.eval_suite_id == "frontend_smoke"
    assert props.input.question_count == 1
    assert props.input.run_label == "运行评估"
    assert props.input.can_run is True
    assert props.report is None
    assert props.tab_order == (
        ComponentId.EVALUATION_SUITE,
        ComponentId.EVALUATION_RUN,
    )


def test_build_evaluation_page_props_renders_passed_report() -> None:
    state = EvaluationPageState(
        context=_context(),
        latest_report=_report(release_gate_passed=True),
    )

    props = build_evaluation_page_props(state, Locale.EN)

    assert props.report is not None
    assert props.report.gate_status is ReleaseGateStatus.PASSED
    assert props.report.gate_label == "Release gate passed"
    assert props.report.tone == "success"
    assert props.report.score_label == "Overall score: 100%"
    assert props.report.cases_label == "2/2 cases passed"
    assert props.report.failed_cases_label == "0 failed cases"
    assert props.report.failed_cases == ()
    assert props.tab_order == (
        ComponentId.EVALUATION_SUITE,
        ComponentId.EVALUATION_RUN,
        ComponentId.EVALUATION_REPORT,
    )


def test_build_evaluation_page_props_renders_failed_cases() -> None:
    state = EvaluationPageState(
        context=_context(),
        is_running=True,
        latest_report=_report(release_gate_passed=False),
    )

    props = build_evaluation_page_props(state, Locale.EN)

    assert props.input.can_run is False
    assert props.input.running_label == "Running evaluation..."
    assert props.report is not None
    assert props.report.gate_status is ReleaseGateStatus.FAILED
    assert props.report.gate_label == "Release gate failed"
    assert props.report.tone == "danger"
    assert props.report.score_label == "Overall score: 50%"
    assert props.report.cases_label == "1/2 cases passed"
    assert props.report.failed_cases_label == "1 failed cases"
    assert props.report.failed_cases[0].question == "DROP TABLE orders"
    assert props.report.failed_cases[0].trace_id == "trc_failed"
    assert props.report.failed_cases[0].error_code == "SQL_GUARDRAIL_BLOCKED"
    assert props.report.failed_cases[0].score_label == "Overall score: 0%"
    assert props.tab_order == (
        ComponentId.EVALUATION_SUITE,
        ComponentId.EVALUATION_RUN,
        ComponentId.EVALUATION_REPORT,
        ComponentId.EVALUATION_FAILED_CASES,
    )


def _context(locale: Locale = Locale.EN) -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=locale,
        role=UserRole.ANALYST,
        bearer_token="test-token",
    )


def _report(release_gate_passed: bool) -> EvaluationRunViewModel:
    failed_cases = 0 if release_gate_passed else 1
    return EvaluationRunViewModel(
        eval_run_id="eval_001",
        eval_suite_id="frontend_smoke",
        total_cases=2,
        passed_cases=2 - failed_cases,
        failed_cases=failed_cases,
        overall_score=1.0 if release_gate_passed else 0.5,
        average_confidence=0.9,
        metric_breakdown={"sql_safety": 1.0 if release_gate_passed else 0.0},
        failed_cases_detail=(() if release_gate_passed else (_failed_case(),)),
        release_gate_passed=release_gate_passed,
    )


def _failed_case() -> Mapping[str, Any]:
    return {
        "question": "DROP TABLE orders",
        "trace_id": "trc_failed",
        "passed": False,
        "score": 0.0,
        "confidence": 0.0,
        "error_code": "SQL_GUARDRAIL_BLOCKED",
    }
