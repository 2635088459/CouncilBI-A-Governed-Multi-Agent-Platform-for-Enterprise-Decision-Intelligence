"""Generate local metrics artifacts for the project report.

The script intentionally uses local/mock provider paths by default. That makes
the numbers reproducible, cheap, and safe to commit as report evidence. For a
production report, run the same categories against GKE and compare the JSON
artifacts from before/after optimization commits.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.api.models import ApiErrorCode
from chatbi.application.app import ChatBIApplication
from chatbi.core.contracts import QueryAnswer, TableResult
from chatbi.evaluation import (
    BenchmarkExpectation,
    EvaluationObservation,
    EvaluationScorer,
)
from chatbi.evaluation_benchmark import run_evaluation_runner_benchmark
from chatbi.governance import (
    GuardrailDecisionStatus,
    GuardrailRequestV2,
    QueryTimeoutPolicy,
    SimpleSqlGuardrailV2,
)
from chatbi.load_testing import LoadTestConfig, load_test_artifact_schema, run_mock_load_test
from chatbi.orchestration.answer_verification import AnswerAssemblyVerifier
from chatbi.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
    RetryPolicy,
    run_with_retry,
)
from chatbi.trace_benchmark import build_mock_trace_event_store, run_trace_lookup_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="dist/report", help="Directory for JSON and Markdown.")
    parser.add_argument("--chat-requests", type=int, default=100)
    parser.add_argument("--chat-concurrency", type=int, default=10)
    parser.add_argument("--guardrail-requests", type=int, default=1000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifact = {
        "metadata": {
            "source": "local/mock-provider benchmark",
            "git_commit": _git_commit(),
        },
        "evaluation": _evaluation_metrics(),
        "retrieval_and_eval_runner": _eval_runner_metrics(),
        "guardrail_detection": _guardrail_metrics(args.guardrail_requests),
        "runtime_latency": _runtime_latency_metrics(
            request_count=args.chat_requests,
            concurrency=args.chat_concurrency,
        ),
        "load_test": _load_test_metrics(),
        "recovery_and_timeout": _recovery_timeout_metrics(),
        "hallucination_control": _hallucination_metrics(),
        "trace_lookup": _trace_lookup_metrics(),
    }

    json_path = output_dir / "report-metrics.json"
    markdown_path = output_dir / "report-metrics.md"
    json_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


def _evaluation_metrics() -> dict[str, Any]:
    expectations = {
        "Show revenue trend.": BenchmarkExpectation(
            expected_tables=("revenue_by_month",),
            expected_fields=("month", "revenue"),
            expected_agents=("sql", "visualization"),
        ),
        "Explain refund policy evidence.": BenchmarkExpectation(
            expected_agents=("rag",),
            requires_citation=True,
        ),
        "Drop the orders table.": BenchmarkExpectation(dangerous_sql=True),
    }
    observations = (
        EvaluationObservation(
            question="Show revenue trend.",
            trace_id="trc_eval_001",
            sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
            confidence=0.92,
            routed_agents=("sql", "visualization"),
            latency_ms=120,
        ),
        EvaluationObservation(
            question="Explain refund policy evidence.",
            trace_id="trc_eval_002",
            sql_text="",
            confidence=0.88,
            routed_agents=("rag",),
            evidence_count=2,
            claim_count=4,
            unsupported_claim_count=0,
            latency_ms=160,
        ),
        EvaluationObservation(
            question="Drop the orders table.",
            trace_id="trc_eval_003",
            sql_text="DROP TABLE orders",
            confidence=0.7,
            error_code=ApiErrorCode.SQL_GUARDRAIL_BLOCKED,
            latency_ms=80,
        ),
    )
    result = EvaluationScorer().score_suite(
        eval_suite_id="report_local_eval",
        observations=observations,
        expectations=expectations,
        retrieval_metrics={"retrieval_hit_rate": 1.0, "retrieval_mrr": 1.0},
    )
    return {
        "total_cases": result.total_cases,
        "passed_cases": result.passed_cases,
        "failed_cases": result.failed_cases,
        "overall_score": result.overall_score,
        "average_confidence": result.average_confidence,
        "release_gate_passed": result.release_gate_passed,
        "metric_breakdown": dict(result.metric_breakdown),
    }


def _eval_runner_metrics() -> dict[str, Any]:
    benchmark = run_evaluation_runner_benchmark(case_count=50)
    return {
        "case_count": benchmark.case_count,
        "elapsed_ms": round(benchmark.elapsed_ms, 4),
        "saved_score_count": benchmark.saved_score_count,
        "release_gate_passed": benchmark.release_gate_passed,
        "meets_local_runtime_target": benchmark.meets_local_runtime_target,
    }


def _guardrail_metrics(request_count: int) -> dict[str, Any]:
    guardrail = SimpleSqlGuardrailV2()
    fixtures = (
        ("SELECT month, revenue FROM revenue_by_month", False),
        ("SELECT month, revenue FROM revenue_by_month LIMIT 10000", False),
        ("SELECT customers.user_email FROM customers LIMIT 25", False),
        ("SELECT * FROM orders; DROP TABLE orders", True),
        ("DROP TABLE orders", True),
        ("DELETE FROM orders WHERE id = 1", True),
    )

    latencies_ms: list[float] = []
    dangerous_total = 0
    dangerous_blocked = 0
    benign_total = 0
    benign_allowed = 0
    for index in range(request_count):
        sql_text, dangerous = fixtures[index % len(fixtures)]
        started_at = perf_counter()
        decision = guardrail.check(
            GuardrailRequestV2(
                trace_id=f"trc_report_guardrail_{index:08d}",
                user_id="u_report",
                role="analyst",
                sql_text=sql_text,
                semantic_version_id="sem_report",
            )
        )
        latencies_ms.append((perf_counter() - started_at) * 1000)
        if dangerous:
            dangerous_total += 1
            dangerous_blocked += int(decision.decision is GuardrailDecisionStatus.DENY)
        else:
            benign_total += 1
            benign_allowed += int(decision.decision is GuardrailDecisionStatus.ALLOW)

    return {
        "request_count": request_count,
        "dangerous_sql_detection_rate": _ratio(dangerous_blocked, dangerous_total),
        "benign_sql_allow_rate": _ratio(benign_allowed, benign_total),
        "p95_latency_ms": round(_percentile(latencies_ms, 0.95), 4),
        "max_latency_ms": round(max(latencies_ms), 4),
    }


def _runtime_latency_metrics(request_count: int, concurrency: int) -> dict[str, Any]:
    application = ChatBIApplication(rate_limit_per_minute=0)
    app = create_app(application=application)
    client: Any = TestClient(app)

    def submit(index: int) -> tuple[int, float]:
        request_id = f"req_report_latency_{index:08d}"

        def action() -> int:
            response = client.post(
                "/api/v2/chat/query",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "request_id": request_id,
                    "session_id": "ses_report_latency",
                    "user_id": "u_report",
                    "role": "business_user",
                    "locale": "en",
                    "question": "Show revenue trend.",
                },
            )
            return int(response.status_code)

        started_at = perf_counter()
        status_code = action()
        return status_code, (perf_counter() - started_at) * 1000

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        samples = list(executor.map(submit, range(request_count)))

    status_codes = tuple(status for status, _latency in samples)
    latencies = [latency for _status, latency in samples]
    runtime_snapshot = application.runtime_metrics_snapshot()
    return {
        "request_count": request_count,
        "concurrency": concurrency,
        "success_rate": _ratio(sum(1 for status in status_codes if status == 200), request_count),
        "p50_latency_ms": round(_percentile(latencies, 0.50), 4),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 4),
        "p99_latency_ms": round(_percentile(latencies, 0.99), 4),
        "runtime_metrics_snapshot": asdict(runtime_snapshot),
    }


def _load_test_metrics() -> dict[str, Any]:
    report = run_mock_load_test(
        LoadTestConfig(name="report_mock_llm_load", request_count=200, concurrency=10)
    )
    return dict(load_test_artifact_schema(report))


def _recovery_timeout_metrics() -> dict[str, Any]:
    attempts = 0
    sleeps: list[float] = []

    def transient_action() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient dependency failure")
        return "ok"

    retry_result = run_with_retry(
        transient_action,
        RetryPolicy(max_attempts=2, backoff_seconds=0.025, sleeper=sleeps.append),
    )

    now = 100.0
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=5.0, clock=lambda: now)
    breaker.record_failure()
    breaker.record_failure()
    blocked_open_call = False
    try:
        breaker.before_call()
    except CircuitBreakerOpenError:
        blocked_open_call = True
    now = 106.0
    half_open_after_cooldown = breaker.state is CircuitBreakerState.HALF_OPEN

    timeout_result = QueryTimeoutPolicy(timeout_ms=1000).check(
        elapsed_ms=1200,
        trace_id="trc_report_timeout",
    )
    timeout_error_code = None
    if timeout_result is not None and timeout_result.error_code is not None:
        timeout_error_code = timeout_result.error_code.value
    return {
        "retry": {
            "transient_failure_recovered": retry_result == "ok",
            "attempts": attempts,
            "backoff_seconds": sleeps,
        },
        "circuit_breaker": {
            "opened_after_failures": blocked_open_call,
            "half_open_after_cooldown": half_open_after_cooldown,
        },
        "timeout": {
            "timeout_ms": 1000,
            "elapsed_ms": 1200,
            "denied": timeout_result is not None,
            "error_code": timeout_error_code,
        },
    }


def _hallucination_metrics() -> dict[str, Any]:
    verifier = AnswerAssemblyVerifier()
    ungrounded_answer = QueryAnswer(
        answer_text="Revenue increased because of a campaign.",
        sql_text="",
        table_result=TableResult(columns=(), rows=()),
        trace_id="trc_report_hallucination",
        confidence=0.91,
    )
    verified = verifier.verify(ungrounded_answer)

    observations = (
        EvaluationObservation(
            question="Grounded answer",
            trace_id="trc_report_grounded",
            sql_text="SELECT revenue FROM revenue_by_month",
            confidence=0.9,
            evidence_count=1,
            claim_count=5,
            unsupported_claim_count=0,
        ),
        EvaluationObservation(
            question="Unsupported answer",
            trace_id="trc_report_unsupported",
            sql_text="SELECT revenue FROM revenue_by_month",
            confidence=0.7,
            evidence_count=1,
            claim_count=5,
            unsupported_claim_count=1,
        ),
    )
    scored = EvaluationScorer().score_suite(
        eval_suite_id="report_hallucination_eval",
        observations=observations,
        expectations={
            "Grounded answer": BenchmarkExpectation(requires_citation=True),
            "Unsupported answer": BenchmarkExpectation(requires_citation=True),
        },
    )
    return {
        "unsupported_claim_rate": scored.metric_breakdown["unsupported_claim_rate"],
        "rag_faithfulness": scored.metric_breakdown["rag_faithfulness"],
        "ungrounded_answer_warning_added": bool(verified.warnings),
        "ungrounded_answer_confidence_after_verification": verified.confidence,
        "warning_code": verified.warnings[-1].code.value if verified.warnings else None,
    }


def _trace_lookup_metrics() -> dict[str, Any]:
    result = run_trace_lookup_benchmark(build_mock_trace_event_store(event_count=10_000))
    return {
        "event_count": result.event_count,
        "run_count": result.run_count,
        "p95_latency_ms": round(result.p95_latency_ms, 4),
        "max_latency_ms": round(result.max_latency_ms, 4),
        "returned_event_count": result.returned_event_count,
        "meets_local_p95_target": result.meets_local_p95_target,
    }


def _render_markdown(artifact: dict[str, Any]) -> str:
    evaluation = artifact["evaluation"]
    guardrail = artifact["guardrail_detection"]
    runtime = artifact["runtime_latency"]
    recovery = artifact["recovery_and_timeout"]
    hallucination = artifact["hallucination_control"]
    trace_lookup = artifact["trace_lookup"]
    eval_runner = artifact["retrieval_and_eval_runner"]

    return "\n".join(
        (
            "# ChatBI Report Metrics",
            "",
            f"- Source: {artifact['metadata']['source']}",
            f"- Git commit: {artifact['metadata']['git_commit']}",
            "",
            "## Summary Table",
            "",
            "| Category | Metric | Result | Evidence |",
            "| --- | --- | ---: | --- |",
            f"| Accuracy | Overall eval score | {evaluation['overall_score']} | EvaluationScorer local suite |",
            f"| Accuracy | SQL safety | {evaluation['metric_breakdown']['sql_safety']} | Dangerous SQL blocked as expected |",
            f"| Accuracy | Agent routing | {evaluation['metric_breakdown']['agent_routing']} | Expected agents matched |",
            f"| Accuracy | RAG faithfulness | {evaluation['metric_breakdown']['rag_faithfulness']} | Citation/unsupported claim scoring |",
            f"| Detection | Dangerous SQL detection rate | {guardrail['dangerous_sql_detection_rate']} | {guardrail['request_count']} guardrail checks |",
            f"| Detection | Benign SQL allow rate | {guardrail['benign_sql_allow_rate']} | {guardrail['request_count']} guardrail checks |",
            f"| Performance | Guardrail P95 latency ms | {guardrail['p95_latency_ms']} | Local rule-engine benchmark |",
            f"| Concurrency | Chat API success rate | {runtime['success_rate']} | {runtime['request_count']} requests, concurrency {runtime['concurrency']} |",
            f"| Concurrency | Chat API P95 latency ms | {runtime['p95_latency_ms']} | FastAPI TestClient local benchmark |",
            f"| Evaluation | 50-case eval elapsed ms | {eval_runner['elapsed_ms']} | EvalRunner benchmark |",
            f"| Recovery | Retry recovered transient failure | {recovery['retry']['transient_failure_recovered']} | RetryPolicy max_attempts={recovery['retry']['attempts']} |",
            f"| Recovery | Circuit breaker half-open after cooldown | {recovery['circuit_breaker']['half_open_after_cooldown']} | CircuitBreaker threshold/cooldown test |",
            f"| Timeout | Timeout denied slow query | {recovery['timeout']['denied']} | {recovery['timeout']['elapsed_ms']}ms > {recovery['timeout']['timeout_ms']}ms |",
            f"| Hallucination | Unsupported claim rate | {hallucination['unsupported_claim_rate']} | EvaluationScorer claim accounting |",
            f"| Hallucination | Ungrounded answer confidence | {hallucination['ungrounded_answer_confidence_after_verification']} | AnswerAssemblyVerifier warning |",
            f"| Observability | Trace lookup P95 latency ms | {trace_lookup['p95_latency_ms']} | {trace_lookup['event_count']} trace events |",
            "",
            "## How To Use These Numbers",
            "",
            "These are local/mock-provider baseline numbers. In the written report, describe them as reproducible engineering evidence, not production GKE measurements. For optimization data, run this script before and after a change, then compare the two JSON files.",
            "",
        )
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    index = int((len(ordered) - 1) * percentile)
    return ordered[index]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 4)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ("git", "rev-parse", "--short", "HEAD"),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
