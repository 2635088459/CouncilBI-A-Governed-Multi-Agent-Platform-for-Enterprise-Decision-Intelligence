"""Run an expanded GKE correctness suite against the staging chat endpoint."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast


GOLDEN_CASES = (
    ("revenue_trend_basic", "Show revenue trend.", True),
    ("revenue_trend_chart", "Create a chart for revenue trend.", True),
    ("monthly_revenue", "What is monthly revenue?", False),
    ("revenue_by_month", "List revenue by month.", False),
    ("business_revenue_summary", "Summarize the revenue trend for business users.", False),
    ("visualize_monthly_revenue", "Visualize monthly revenue.", True),
    ("trend_plot", "Plot the revenue trend.", True),
    ("revenue_table", "Return a table of monthly revenue.", False),
    ("six_month_revenue", "Show the six month revenue trend.", True),
    ("executive_revenue_view", "Give me an executive view of revenue trend.", False),
    ("revenue_over_time", "How did revenue change over time?", False),
    ("chart_revenue_over_time", "Can you chart revenue over time?", True),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", default="dist/report")
    parser.add_argument("--output-prefix", default="gke-extended-correctness")
    args = parser.parse_args()

    run_id = f"{int(time.time() * 1000)}"
    results = [
        _run_case(args.base_url.rstrip("/"), run_id, index, case_id, question, needs_visualization)
        for index, (case_id, question, needs_visualization) in enumerate(GOLDEN_CASES)
    ]
    passed = sum(1 for result in results if result["passed"])
    artifact = {
        "source": "gke-staging-extended-correctness",
        "base_url": args.base_url.rstrip("/"),
        "total_cases": len(results),
        "passed_cases": passed,
        "failed_cases": len(results) - passed,
        "correctness_rate": round(passed / len(results), 4),
        "average_confidence": round(
            sum(float(result["confidence"]) for result in results) / len(results),
            4,
        ),
        "results": results,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{args.output_prefix}.json"
    markdown_path = output_dir / f"{args.output_prefix}.md"
    json_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


def _run_case(
    base_url: str,
    run_id: str,
    index: int,
    case_id: str,
    question: str,
    needs_visualization: bool,
) -> dict[str, Any]:
    payload = {
        "request_id": f"req_gke_correctness_{run_id}_{index:03d}",
        "session_id": f"ses_gke_correctness_{run_id}",
        "user_id": "u_gke_correctness",
        "role": "business_user",
        "locale": "en",
        "question": question,
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

    table = _mapping(response_data.get("table_result"))
    columns = {str(column) for column in _list(table.get("columns"))}
    rows = _list(table.get("rows"))
    agents = {
        str(item.get("agent_name"))
        for item in _agent_timeline(response_data)
        if item.get("status") == "succeeded"
    }
    required_agents = {"orchestrator", "sql_agent", "verifier_agent", "answer_synthesis"}
    if needs_visualization:
        required_agents.add("visualization_agent")
    passed = (
        status_code == 200
        and {"month", "revenue"}.issubset(columns)
        and len(rows) >= 1
        and bool(response_data.get("answer_text"))
        and required_agents.issubset(agents)
    )
    return {
        "case_id": case_id,
        "question": question,
        "needs_visualization": needs_visualization,
        "passed": passed,
        "status_code": status_code,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 4),
        "confidence": float(response_data.get("confidence", 0.0)),
        "actual_columns": sorted(columns),
        "row_count": len(rows),
        "succeeded_agents": sorted(agents),
        "error": error,
    }


def _agent_timeline(response_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _mapping(cast(object, item))
        for item in _list(response_data.get("agent_timeline"))
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


def _render_markdown(artifact: dict[str, Any]) -> str:
    lines = [
        "# GKE Extended Correctness",
        "",
        f"- Base URL: {artifact['base_url']}",
        f"- Correctness rate: {artifact['correctness_rate']}",
        f"- Passed cases: {artifact['passed_cases']}/{artifact['total_cases']}",
        f"- Average confidence: {artifact['average_confidence']}",
        "",
        "| Case | Passed | Status | Needs Viz | Confidence | Rows | Latency ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in artifact["results"]:
        lines.append(
            f"| {result['case_id']} | {result['passed']} | {result['status_code']} | "
            f"{result['needs_visualization']} | {result['confidence']} | "
            f"{result['row_count']} | {result['latency_ms']} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
