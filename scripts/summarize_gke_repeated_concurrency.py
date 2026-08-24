"""Summarize repeated GKE concurrency benchmark runs."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--output", default="dist/report/gke-repeated-concurrency-summary.md")
    parser.add_argument("--baseline-p95-ms", type=float, default=256.9212)
    args = parser.parse_args()

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for file_name in args.files:
        row = _row(Path(file_name))
        grouped[int(row["concurrency"])].append(row)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _render_markdown(grouped=grouped, baseline_p95_ms=args.baseline_p95_ms),
        encoding="utf-8",
    )
    print(f"Wrote {output}")


def _row(path: Path) -> dict[str, Any]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    chat = artifact["chat_query_load"]
    latency = chat["latency_ms"]
    guardrail = artifact["guardrail_checks"]
    return {
        "file": path.name,
        "concurrency": int(chat["concurrency"]),
        "success_rate": float(chat["success_rate"]),
        "throughput_rps": float(chat["throughput_rps"]),
        "p95_latency_ms": float(latency["p95"]),
        "p99_latency_ms": float(latency["p99"]),
        "agent_step_success_rate": float(chat["agent_step_success_rate"]),
        "multi_agent_success_rate": float(chat["multi_agent_collaboration_success_rate"]),
        "sql_detection_rate": float(guardrail["dangerous_sql_detection_rate"]),
        "guardrail_p95_ms": float(guardrail["p95_latency_ms"]),
    }


def _render_markdown(
    *,
    grouped: dict[int, list[dict[str, Any]]],
    baseline_p95_ms: float,
) -> str:
    lines = [
        "# GKE Repeated Concurrency Summary",
        "",
        "| Concurrency | Runs | Avg success | Avg RPS | Best RPS | Avg P95 ms | Worst P95 ms | Avg P99 ms | Agent success | Multi-agent success | SQL detection | Guardrail P95 ms |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    best_current_p95 = None
    for concurrency in sorted(grouped):
        rows = grouped[concurrency]
        avg_success = _avg(rows, "success_rate")
        avg_rps = _avg(rows, "throughput_rps")
        best_rps = max(row["throughput_rps"] for row in rows)
        avg_p95 = _avg(rows, "p95_latency_ms")
        worst_p95 = max(row["p95_latency_ms"] for row in rows)
        avg_p99 = _avg(rows, "p99_latency_ms")
        agent_success = _avg(rows, "agent_step_success_rate")
        multi_agent_success = _avg(rows, "multi_agent_success_rate")
        sql_detection = _avg(rows, "sql_detection_rate")
        guardrail_p95 = _avg(rows, "guardrail_p95_ms")
        best_current_p95 = avg_p95 if best_current_p95 is None else min(best_current_p95, avg_p95)
        lines.append(
            f"| {concurrency} | {len(rows)} | {avg_success} | {avg_rps} | {round(best_rps, 4)} | "
            f"{avg_p95} | {round(worst_p95, 4)} | {avg_p99} | {agent_success} | "
            f"{multi_agent_success} | {sql_detection} | {guardrail_p95} |"
        )

    lines.extend(["", "## Optimization Lift", ""])
    if best_current_p95 is None:
        lines.append("No benchmark rows were available.")
    else:
        improvement = round((baseline_p95_ms - best_current_p95) / baseline_p95_ms * 100, 2)
        lines.append(f"- Prior single-run baseline P95 latency: {baseline_p95_ms} ms")
        lines.append(f"- Best repeated-run average P95 latency: {round(best_current_p95, 4)} ms")
        lines.append(f"- Repeated-run P95 latency improvement: {improvement}%")
    lines.append("")
    return "\n".join(lines)


def _avg(rows: list[dict[str, Any]], key: str) -> float:
    return round(statistics.fmean(float(row[key]) for row in rows), 4)


if __name__ == "__main__":
    main()
