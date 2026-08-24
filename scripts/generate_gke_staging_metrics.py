"""Collect HTTP metrics from a deployed GKE staging ChatBI endpoint."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--guardrail-requests", type=int, default=100)
    parser.add_argument("--output-dir", default="dist/report")
    parser.add_argument("--output-prefix", default="gke-staging-metrics")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = time.perf_counter()
    samples = _run_chat_query_load(
        base_url=args.base_url.rstrip("/"),
        request_count=args.requests,
        concurrency=args.concurrency,
    )
    elapsed_seconds = time.perf_counter() - started_at
    latencies = [sample["latency_ms"] for sample in samples]
    succeeded = sum(1 for sample in samples if sample["succeeded"])
    chat_summary = _chat_summary(samples=samples, elapsed_seconds=elapsed_seconds)
    guardrail_summary = _run_guardrail_checks(
        base_url=args.base_url.rstrip("/"),
        request_count=args.guardrail_requests,
    )
    artifact = {
        "source": "gke-staging-http",
        "base_url": args.base_url.rstrip("/"),
        "chat_query_load": {
            "request_count": args.requests,
            "concurrency": args.concurrency,
            "elapsed_seconds": round(elapsed_seconds, 4),
            "throughput_rps": round(args.requests / elapsed_seconds, 4),
            "succeeded_requests": succeeded,
            "failed_requests": args.requests - succeeded,
            "success_rate": round(succeeded / args.requests, 4),
            "latency_ms": {
                "p50": round(_percentile(latencies, 0.50), 4),
                "p95": round(_percentile(latencies, 0.95), 4),
                "p99": round(_percentile(latencies, 0.99), 4),
                "max": round(max(latencies), 4),
                "mean": round(statistics.fmean(latencies), 4),
            },
            **chat_summary,
        },
        "guardrail_checks": guardrail_summary,
        "samples": samples,
    }

    json_path = output_dir / f"{args.output_prefix}.json"
    markdown_path = output_dir / f"{args.output_prefix}.md"
    json_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


def _run_chat_query_load(
    *,
    base_url: str,
    request_count: int,
    concurrency: int,
) -> list[dict[str, Any]]:
    def submit(index: int) -> dict[str, Any]:
        payload = {
            "request_id": f"req_gke_load_{index:08d}",
            "session_id": "ses_gke_load",
            "user_id": "u_gke_load",
            "role": "business_user",
            "locale": "en",
            "question": "Show revenue trend.",
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/v2/chat/query",
            data=data,
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started_at = time.perf_counter()
        status_code = 0
        trace_id = None
        error = None
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                status_code = response.status
                response_body = _json_object(response.read().decode("utf-8"))
                trace_id = response_body.get("trace_id")
                data = _mapping(response_body.get("data"))
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            error = str(exc)
            data = {}
        except Exception as exc:
            error = type(exc).__name__
            data = {}
        latency_ms = (time.perf_counter() - started_at) * 1000
        data_dict = _mapping(data)
        agent_timeline = data_dict.get("agent_timeline")
        agents = [
            _mapping(cast(object, item))
            for item in _list(agent_timeline)
            if isinstance(item, Mapping)
        ]
        table_result = data_dict.get("table_result")
        rows = _list(_mapping(table_result).get("rows"))
        return {
            "index": index,
            "status_code": status_code,
            "succeeded": status_code == 200,
            "latency_ms": round(latency_ms, 4),
            "trace_id": trace_id,
            "error": error,
            "confidence": data_dict.get("confidence"),
            "guardrail_blocked": data_dict.get("guardrail_blocked"),
            "row_count": len(rows),
            "agent_timeline": agents,
        }

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        return list(executor.map(submit, range(request_count)))


def _run_guardrail_checks(*, base_url: str, request_count: int) -> dict[str, Any]:
    fixtures = (
        ("SELECT month, revenue FROM revenue_by_month", False),
        ("SELECT month, revenue FROM revenue_by_month LIMIT 10000", False),
        ("SELECT customers.user_email FROM customers LIMIT 25", False),
        ("SELECT * FROM orders; DROP TABLE orders", True),
        ("DROP TABLE orders", True),
        ("DELETE FROM orders WHERE id = 1", True),
    )
    samples: list[dict[str, Any]] = []
    for index in range(request_count):
        sql_text, dangerous = fixtures[index % len(fixtures)]
        payload = {
            "user_id": "u_gke_guardrail",
            "role": "analyst",
            "sql_text": sql_text,
            "semantic_version_id": "sem_report",
        }
        request = urllib.request.Request(
            f"{base_url}/api/v1/sql/guardrail/check",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
                "X-Trace-Id": f"trc_gke_guardrail_{index:08d}",
            },
            method="POST",
        )
        started_at = time.perf_counter()
        status_code = 0
        decision = None
        error = None
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                status_code = response.status
                body = _json_object(response.read().decode("utf-8"))
                data = _mapping(body.get("data"))
                raw_decision = data.get("decision")
                decision = raw_decision if isinstance(raw_decision, str) else None
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            error = str(exc)
        except Exception as exc:
            error = type(exc).__name__
        samples.append(
            {
                "index": index,
                "dangerous": dangerous,
                "status_code": status_code,
                "decision": decision,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 4),
                "error": error,
            }
        )

    dangerous_samples = [sample for sample in samples if sample["dangerous"]]
    benign_samples = [sample for sample in samples if not sample["dangerous"]]
    latencies = [sample["latency_ms"] for sample in samples]
    return {
        "request_count": request_count,
        "dangerous_sql_detection_rate": _ratio(
            sum(1 for sample in dangerous_samples if sample["decision"] == "deny"),
            len(dangerous_samples),
        ),
        "benign_sql_allow_rate": _ratio(
            sum(1 for sample in benign_samples if sample["decision"] == "allow"),
            len(benign_samples),
        ),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 4),
        "p99_latency_ms": round(_percentile(latencies, 0.99), 4),
        "failed_requests": sum(1 for sample in samples if sample["status_code"] != 200),
        "samples": samples,
    }


def _chat_summary(*, samples: list[dict[str, Any]], elapsed_seconds: float) -> dict[str, Any]:
    successful_samples = [sample for sample in samples if sample["succeeded"]]
    planned_agent_steps: list[dict[str, Any]] = []
    for sample in successful_samples:
        for item in _sample_agent_timeline(sample):
            if item.get("status") != "not_planned":
                planned_agent_steps.append(item)
    succeeded_agent_steps = [
        item for item in planned_agent_steps if item.get("status") == "succeeded"
    ]
    multi_agent_successes = 0
    for sample in successful_samples:
        agent_names = {
            str(item.get("agent_name"))
            for item in _sample_agent_timeline(sample)
            if item.get("status") == "succeeded"
        }
        if {"orchestrator", "sql_agent", "visualization_agent", "verifier_agent", "answer_synthesis"}.issubset(
            agent_names
        ):
            multi_agent_successes += 1

    confidences = [
        float(sample["confidence"])
        for sample in successful_samples
        if isinstance(sample.get("confidence"), int | float)
    ]
    row_counts = [int(sample["row_count"]) for sample in successful_samples]
    return {
        "throughput_note": "throughput_rps is request_count divided by wall-clock elapsed_seconds",
        "average_confidence": round(statistics.fmean(confidences), 4) if confidences else 0.0,
        "average_rows_returned": round(statistics.fmean(row_counts), 4) if row_counts else 0.0,
        "tool_call_count": len(planned_agent_steps),
        "average_tool_calls_per_successful_request": round(
            len(planned_agent_steps) / len(successful_samples), 4
        )
        if successful_samples
        else 0.0,
        "agent_step_success_rate": _ratio(len(succeeded_agent_steps), len(planned_agent_steps)),
        "multi_agent_collaboration_success_rate": _ratio(
            multi_agent_successes,
            len(successful_samples),
        ),
        "guardrail_blocked_rate": _ratio(
            sum(1 for sample in successful_samples if sample.get("guardrail_blocked") is True),
            len(successful_samples),
        ),
        "elapsed_seconds": round(elapsed_seconds, 4),
    }


def _sample_agent_timeline(sample: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _mapping(cast(object, item))
        for item in _list(sample.get("agent_timeline"))
        if isinstance(item, Mapping)
    ]


def _json_object(text: str) -> dict[str, Any]:
    value: object = json.loads(text)
    return _mapping(value)


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    raw_mapping = cast(Mapping[object, object], value)
    return {str(key): cast(Any, item) for key, item in raw_mapping.items()}


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return list(cast(list[object], value))


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
    return ordered[index]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 4)


def _render_markdown(artifact: dict[str, Any]) -> str:
    chat = artifact["chat_query_load"]
    latency = chat["latency_ms"]
    guardrail = artifact["guardrail_checks"]
    return "\n".join(
        (
            "# GKE Staging Metrics",
            "",
            f"- Base URL: {artifact['base_url']}",
            f"- Chat requests: {chat['request_count']}",
            f"- Chat concurrency: {chat['concurrency']}",
            f"- Guardrail checks: {guardrail['request_count']}",
            "",
            "| Metric | Result |",
            "| --- | ---: |",
            f"| Chat success rate | {chat['success_rate']} |",
            f"| Chat throughput RPS | {chat['throughput_rps']} |",
            f"| Succeeded chat requests | {chat['succeeded_requests']} |",
            f"| Failed chat requests | {chat['failed_requests']} |",
            f"| P50 latency ms | {latency['p50']} |",
            f"| P95 latency ms | {latency['p95']} |",
            f"| P99 latency ms | {latency['p99']} |",
            f"| Max latency ms | {latency['max']} |",
            f"| Mean latency ms | {latency['mean']} |",
            f"| Average confidence | {chat['average_confidence']} |",
            f"| Average rows returned | {chat['average_rows_returned']} |",
            f"| Total tool/agent calls | {chat['tool_call_count']} |",
            f"| Avg tool/agent calls per successful request | {chat['average_tool_calls_per_successful_request']} |",
            f"| Agent step success rate | {chat['agent_step_success_rate']} |",
            f"| Multi-agent collaboration success rate | {chat['multi_agent_collaboration_success_rate']} |",
            f"| Chat guardrail blocked rate | {chat['guardrail_blocked_rate']} |",
            f"| Dangerous SQL detection rate | {guardrail['dangerous_sql_detection_rate']} |",
            f"| Benign SQL allow rate | {guardrail['benign_sql_allow_rate']} |",
            f"| Guardrail P95 latency ms | {guardrail['p95_latency_ms']} |",
            f"| Guardrail P99 latency ms | {guardrail['p99_latency_ms']} |",
            f"| Guardrail failed requests | {guardrail['failed_requests']} |",
            "",
        )
    )


if __name__ == "__main__":
    main()
