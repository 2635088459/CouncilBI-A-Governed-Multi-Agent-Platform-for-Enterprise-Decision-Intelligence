from chatbi.evaluation_observability_v2 import (
    EvalCase,
    EvalFailureRecord,
    EvalRunReport,
    EvaluationScorer,
    HumanAcceptanceExample,
    InMemoryTraceEventStore,
    LogLevel,
    ObservabilityLogger,
    ReleaseGateRunner,
    TraceEvent,
    TraceEventStatus,
    build_mock_eval_cases,
    build_mock_trace_event_store,
    default_release_gate_ci_plan,
    eval_run_report,
    evaluation_sql_safety_check,
    human_acceptance_check,
    load_eval_cases,
    render_observability_json_log,
    render_runtime_metrics,
    run_evaluation_runner_benchmark,
    run_trace_lookup_benchmark,
)


def test_evaluation_observability_v2_exports_core_workflow_objects() -> None:
    assert EvalCase.__name__ == "EvalCase"
    assert EvalFailureRecord.__name__ == "EvalFailureRecord"
    assert EvalRunReport.__name__ == "EvalRunReport"
    assert EvaluationScorer.__name__ == "EvaluationScorer"
    assert HumanAcceptanceExample.__name__ == "HumanAcceptanceExample"
    assert InMemoryTraceEventStore.__name__ == "InMemoryTraceEventStore"
    assert ReleaseGateRunner.__name__ == "ReleaseGateRunner"
    assert TraceEvent.__name__ == "TraceEvent"
    assert TraceEventStatus.SUCCEEDED.value == "succeeded"


def test_evaluation_observability_v2_exports_helpers_that_run() -> None:
    cases = build_mock_eval_cases(case_count=2)
    loaded_cases = load_eval_cases(({"case_id": "case_loaded", "question": "Show revenue."},))
    trace_store = build_mock_trace_event_store(event_count=3)
    trace_result = run_trace_lookup_benchmark(trace_store, run_count=1)
    eval_result = run_evaluation_runner_benchmark(case_count=2)
    metrics_text = render_runtime_metrics()
    safety_check = evaluation_sql_safety_check(1.0)
    ci_plan = default_release_gate_ci_plan()
    log_line = render_observability_json_log(
        ObservabilityLogger().record(
            trace_id="trc_facade_log",
            level=LogLevel.INFO,
            message="Facade log.",
            endpoint="/api/v1/chat/query",
            user_id="u_001",
        )
    )

    assert len(cases) == 2
    assert loaded_cases[0].case_id == "case_loaded"
    assert trace_result.returned_event_count == 1
    assert eval_result.saved_score_count == 2
    assert "chatbi_api_request_count_total" in metrics_text
    assert safety_check.passed is True
    assert eval_run_report.__name__ == "eval_run_report"
    assert human_acceptance_check.__name__ == "human_acceptance_check"
    assert ci_plan.step_names[0].value == "pyright"
    assert '"trace_id":"trc_facade_log"' in log_line
