"""Collect sustained GKE HTTP benchmark metrics with unique request IDs."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, cast


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--duration-seconds", type=float, default=600.0)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--target-rps", type=float, default=20.0)
    parser.add_argument("--output-dir", default="dist/report")
    parser.add_argument("--output-prefix", default="gke-sustained-benchmark")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = _run_sustained_benchmark(
        base_url=args.base_url.rstrip("/"),
        duration_seconds=args.duration_seconds,
        concurrency=args.concurrency,
        target_rps=args.target_rps,
    )

    json_path = output_dir / f"{args.output_prefix}.json"
    markdown_path = output_dir / f"{args.output_prefix}.md"
    json_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


def _run_sustained_benchmark(
    *,
    base_url: str,
    duration_seconds: float,
    concurrency: int,
    target_rps: float,
) -> dict[str, Any]:
    run_id = f"{int(time.time() * 1000)}"
    started_at = time.perf_counter()
    deadline = started_at + duration_seconds
    interval_seconds = 1 / target_rps
    futures: list[Future[dict[str, Any]]] = []
    submitted = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        next_submit_at = time.perf_counter()
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            if now < next_submit_at:
                time.sleep(min(next_submit_at - now, 0.05))
                continue
            futures.append(executor.submit(_submit_chat_query, base_url, run_id, submitted))
            submitted += 1
            next_submit_at += interval_seconds

        samples = [future.result() for future in as_completed(futures)]

    elapsed_seconds = time.perf_counter() - started_at
    latencies = [float(sample["latency_ms"]) for sample in samples]
    succeeded_samples = [sample for sample in samples if sample["succeeded"]]
    planned_agent_steps = [
        item
        for sample in succeeded_samples
        for item in _sample_agent_timeline(sample)
        if item.get("status") != "not_planned"
    ]
    succeeded_agent_steps = [
        item for item in planned_agent_steps if item.get("status") == "succeeded"
    ]
    multi_agent_successes = sum(
        1 for sample in succeeded_samples if _has_required_agents(sample)
    )
    confidences = [
        float(sample["confidence"])
        for sample in succeeded_samples
        if isinstance(sample.get("confidence"), int | float)
    ]
    row_counts = [int(sample["row_count"]) for sample in succeeded_samples]

    return {
        "source": "gke-sustained-http",
        "base_url": base_url,
        "duration_seconds": round(duration_seconds, 4),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "concurrency": concurrency,
        "target_rps": target_rps,
        "request_count": len(samples),
        "succeeded_requests": len(succeeded_samples),
        "failed_requests": len(samples) - len(succeeded_samples),
        "success_rate": _ratio(len(succeeded_samples), len(samples)),
        "throughput_rps": round(len(samples) / elapsed_seconds, 4),
        "latency_ms": {
            "p50": round(_percentile(latencies, 0.50), 4),
            "p95": round(_percentile(latencies, 0.95), 4),
            "p99": round(_percentile(latencies, 0.99), 4),
            "max": round(max(latencies), 4),
            "mean": round(statistics.fmean(latencies), 4),
        },
        "average_confidence": round(statistics.fmean(confidences), 4) if confidences else 0.0,
        "average_rows_returned": round(statistics.fmean(row_counts), 4) if row_counts else 0.0,
        "tool_call_count": len(planned_agent_steps),
        "average_tool_calls_per_successful_request": round(
            len(planned_agent_steps) / len(succeeded_samples),
            4,
        )
        if succeeded_samples
        else 0.0,
        "agent_step_success_rate": _ratio(len(succeeded_agent_steps), len(planned_agent_steps)),
        "multi_agent_collaboration_success_rate": _ratio(
            multi_agent_successes,
            len(succeeded_samples),
        ),
        "status_code_counts": _status_code_counts(samples),
        "samples": samples,
    }


def _submit_chat_query(base_url: str, run_id: str, index: int) -> dict[str, Any]:
    payload = {
        "request_id": f"req_gke_sustained_{run_id}_{index:08d}",
        "session_id": f"ses_gke_sustained_{run_id}",
        "user_id": f"u_gke_sustained_{run_id}",
        "role": "business_user",
        "locale": "en",
        "question": "Show revenue trend.",
    }
    request = urllib.request.Request(
        f"{base_url}/api/v2/chat/query",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started_at = time.perf_counter()
    status_code = 0
    response_data: dict[str, Any] = {}
    error = None
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status_code = response.status
            body = _json_object(response.read().decode("utf-8"))
            response_data = _mapping(body.get("data"))
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        error = str(exc)
    except Exception as exc:
        error = type(exc).__name__

    table_result = _mapping(response_data.get("table_result"))
    rows = _list(table_result.get("rows"))
    agents = [
        _mapping(cast(object, item))
        for item in _list(response_data.get("agent_timeline"))
        if isinstance(item, Mapping)
    ]
    return {
        "index": index,
        "status_code": status_code,
        "succeeded": status_code == 200,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 4),
        "confidence": response_data.get("confidence"),
        "row_count": len(rows),
        "agent_timeline": agents,
        "error": error,
    }


def _sample_agent_timeline(sample: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _mapping(cast(object, item))
        for item in _list(sample.get("agent_timeline"))
        if isinstance(item, Mapping)
    ]


def _has_required_agents(sample: Mapping[str, Any]) -> bool:
    agent_names = {
        str(item.get("agent_name"))
        for item in _sample_agent_timeline(sample)
        if item.get("status") == "succeeded"
    }
    return {"orchestrator", "sql_agent", "verifier_agent", "answer_synthesis"}.issubset(
        agent_names
    )


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
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
    return ordered[index]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 4)


def _status_code_counts(samples: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        key = str(sample["status_code"])
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _render_markdown(artifact: dict[str, Any]) -> str:
    latency = artifact["latency_ms"]
    return "\n".join(
        (
            "# GKE Sustained Benchmark",
            "",
            f"- Base URL: {artifact['base_url']}",
            f"- Duration seconds: {artifact['duration_seconds']}",
            f"- Elapsed seconds: {artifact['elapsed_seconds']}",
            f"- Target RPS: {artifact['target_rps']}",
            f"- Concurrency: {artifact['concurrency']}",
            "",
            "| Metric | Result |",
            "| --- | ---: |",
            f"| Request count | {artifact['request_count']} |",
            f"| Success rate | {artifact['success_rate']} |",
            f"| Throughput RPS | {artifact['throughput_rps']} |",
            f"| P50 latency ms | {latency['p50']} |",
            f"| P95 latency ms | {latency['p95']} |",
            f"| P99 latency ms | {latency['p99']} |",
            f"| Max latency ms | {latency['max']} |",
            f"| Mean latency ms | {latency['mean']} |",
            f"| Average confidence | {artifact['average_confidence']} |",
            f"| Average rows returned | {artifact['average_rows_returned']} |",
            f"| Total tool/agent calls | {artifact['tool_call_count']} |",
            f"| Avg tool/agent calls per successful request | {artifact['average_tool_calls_per_successful_request']} |",
            f"| Agent step success rate | {artifact['agent_step_success_rate']} |",
            f"| Multi-agent collaboration success rate | {artifact['multi_agent_collaboration_success_rate']} |",
            f"| Status code counts | {json.dumps(artifact['status_code_counts'], sort_keys=True)} |",
            "",
        )
    )


if __name__ == "__main__":
    main()
