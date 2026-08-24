"""Summarize GKE concurrency benchmark JSON files into one report table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--output", default="dist/report/gke-concurrency-summary.md")
    parser.add_argument(
        "--baseline-p95-ms",
        type=float,
        default=None,
        help="Optional prior baseline P95 latency for optimization-lift reporting.",
    )
    args = parser.parse_args()

    rows = [_summary_row(Path(file_name)) for file_name in args.files]
    rows.sort(key=lambda row: int(row["concurrency"]))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_markdown(rows, baseline_p95_ms=args.baseline_p95_ms), encoding="utf-8")
    print(f"Wrote {output}")


def _summary_row(path: Path) -> dict[str, Any]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    chat = artifact["chat_query_load"]
    latency = chat["latency_ms"]
    guardrail = artifact["guardrail_checks"]
    return {
        "file": path.name,
        "base_url": artifact["base_url"],
        "requests": chat["request_count"],
        "concurrency": chat["concurrency"],
        "success_rate": chat["success_rate"],
        "throughput_rps": chat["throughput_rps"],
        "p50_latency_ms": latency["p50"],
        "p95_latency_ms": latency["p95"],
        "p99_latency_ms": latency["p99"],
        "mean_latency_ms": latency["mean"],
        "agent_step_success_rate": chat["agent_step_success_rate"],
        "multi_agent_collaboration_success_rate": chat["multi_agent_collaboration_success_rate"],
        "avg_tool_calls": chat["average_tool_calls_per_successful_request"],
        "dangerous_sql_detection_rate": guardrail["dangerous_sql_detection_rate"],
        "guardrail_p95_latency_ms": guardrail["p95_latency_ms"],
    }


def _render_markdown(rows: list[dict[str, Any]], baseline_p95_ms: float | None) -> str:
    best_p95 = min(float(row["p95_latency_ms"]) for row in rows)
    lines = [
        "# GKE Concurrency Summary",
        "",
        "| Concurrency | Requests | Success | Throughput RPS | P50 ms | P95 ms | P99 ms | Agent step success | Multi-agent success | Avg tool calls | SQL detection | Guardrail P95 ms |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {concurrency} | {requests} | {success_rate} | {throughput_rps} | "
            "{p50_latency_ms} | {p95_latency_ms} | {p99_latency_ms} | "
            "{agent_step_success_rate} | {multi_agent_collaboration_success_rate} | "
            "{avg_tool_calls} | {dangerous_sql_detection_rate} | {guardrail_p95_latency_ms} |".format(
                **row
            )
        )

    lines.extend(
        [
            "",
            "## Optimization Lift",
            "",
        ]
    )
    if baseline_p95_ms is None:
        lines.append(
            "No prior baseline was provided. Use `--baseline-p95-ms` with an earlier P95 value to compute latency lift."
        )
    else:
        lift = round((baseline_p95_ms - best_p95) / baseline_p95_ms * 100, 2)
        lines.append(f"- Prior baseline P95 latency: {baseline_p95_ms} ms")
        lines.append(f"- Best current P95 latency: {round(best_p95, 4)} ms")
        lines.append(f"- P95 latency improvement: {lift}%")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
