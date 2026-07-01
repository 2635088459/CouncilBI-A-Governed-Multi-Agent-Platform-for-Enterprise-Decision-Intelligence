"""Public facade for the spec-10 evaluation and observability slice.

The implementation is intentionally split into focused files for teaching:
trace contracts, metrics rendering, eval persistence, release gates, and local
benchmarks each live in their own module. This facade gives callers one stable
import path for the full spec-10 workflow.
"""

from chatbi.evaluation import (
    BenchmarkExpectation,
    EvaluationCase,
    EvaluationMetric,
    EvaluationObservation,
    EvaluationScorer,
    ReleaseGatePolicy,
)
from chatbi.evaluation_benchmark import (
    EvaluationRunnerBenchmarkResult,
    build_mock_eval_cases,
    run_evaluation_runner_benchmark,
)
from chatbi.evaluation_cases import load_eval_cases
from chatbi.evaluation_repository import (
    EvalCase,
    EvalFailureRecord,
    EvalRunRecord,
    EvalRunStatus,
    EvalRunner,
    EvalScore,
    EvaluationRepository,
    InMemoryEvaluationRepository,
    failure_record_from_score,
    simple_sql_fragment_score,
)
from chatbi.evaluation_report import (
    EvalFailureSummary,
    EvalRunReport,
    eval_run_report,
    require_eval_run_report,
)
from chatbi.human_acceptance import (
    HumanAcceptanceExample,
    HumanAcceptanceReview,
    human_acceptance_check,
)
from chatbi.observability import (
    AlertEvaluator,
    AlertEvent,
    AlertRule,
    AlertRuleId,
    AlertSeverity,
    InMemoryObservabilityStore,
    ObservabilitySpan,
    RuntimeRequestSample,
    SloStatus,
    TraceRecorder,
    TraceReplay,
    TraceSpanName,
    TraceSpanStatus,
    default_alert_rules,
)
from chatbi.observability_logs import (
    InMemoryObservabilityLogStore,
    LogLevel,
    LogSanitizer,
    ObservabilityLogRecord,
    ObservabilityLogger,
    observability_log_payload,
    render_observability_json_log,
    render_observability_json_logs,
)
from chatbi.release_gate import (
    ReleaseGateCheckName,
    ReleaseGateCheckResult,
    ReleaseGateCheckStatus,
    ReleaseGateReport,
    ReleaseGateRunner,
    evaluation_sql_safety_check,
    failed_check,
    passed_check,
    skipped_check,
)
from chatbi.release_gate_ci import (
    ReleaseGateCiPlan,
    ReleaseGateCiStep,
    default_release_gate_ci_plan,
    validate_release_gate_ci_order,
)
from chatbi.runtime_metrics import (
    RuntimeMetricsSnapshot,
    render_runtime_metrics,
    runtime_metrics_snapshot,
)
from chatbi.trace_benchmark import (
    TraceLookupBenchmarkResult,
    build_mock_trace_event_store,
    run_trace_lookup_benchmark,
)
from chatbi.trace_events import (
    InMemoryTraceEventStore,
    TraceEvent,
    TraceEventRecorder,
    TraceEventStatus,
)


__all__ = [
    "AlertEvaluator",
    "AlertEvent",
    "AlertRule",
    "AlertRuleId",
    "AlertSeverity",
    "BenchmarkExpectation",
    "EvalCase",
    "EvalFailureRecord",
    "EvalFailureSummary",
    "EvalRunRecord",
    "EvalRunReport",
    "EvalRunStatus",
    "EvalRunner",
    "EvalScore",
    "EvaluationCase",
    "EvaluationMetric",
    "EvaluationObservation",
    "EvaluationRepository",
    "EvaluationRunnerBenchmarkResult",
    "EvaluationScorer",
    "HumanAcceptanceExample",
    "HumanAcceptanceReview",
    "InMemoryEvaluationRepository",
    "InMemoryObservabilityLogStore",
    "InMemoryObservabilityStore",
    "InMemoryTraceEventStore",
    "LogLevel",
    "LogSanitizer",
    "ObservabilityLogRecord",
    "ObservabilityLogger",
    "ObservabilitySpan",
    "ReleaseGateCheckName",
    "ReleaseGateCheckResult",
    "ReleaseGateCheckStatus",
    "ReleaseGateCiPlan",
    "ReleaseGateCiStep",
    "ReleaseGatePolicy",
    "ReleaseGateReport",
    "ReleaseGateRunner",
    "RuntimeMetricsSnapshot",
    "RuntimeRequestSample",
    "SloStatus",
    "TraceEvent",
    "TraceEventRecorder",
    "TraceEventStatus",
    "TraceLookupBenchmarkResult",
    "TraceRecorder",
    "TraceReplay",
    "TraceSpanName",
    "TraceSpanStatus",
    "build_mock_eval_cases",
    "build_mock_trace_event_store",
    "default_alert_rules",
    "default_release_gate_ci_plan",
    "evaluation_sql_safety_check",
    "eval_run_report",
    "failure_record_from_score",
    "failed_check",
    "human_acceptance_check",
    "load_eval_cases",
    "observability_log_payload",
    "passed_check",
    "render_observability_json_log",
    "render_observability_json_logs",
    "render_runtime_metrics",
    "require_eval_run_report",
    "run_evaluation_runner_benchmark",
    "run_trace_lookup_benchmark",
    "runtime_metrics_snapshot",
    "simple_sql_fragment_score",
    "skipped_check",
    "validate_release_gate_ci_order",
]
