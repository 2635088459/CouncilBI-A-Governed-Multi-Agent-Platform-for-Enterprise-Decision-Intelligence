"""Run a small cloud golden correctness smoke suite against GKE staging."""

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
    {
        "case_id": "golden_revenue_trend",
        "question": "Show revenue trend.",
        "expected_agents": {"orchestrator", "sql_agent", "visualization_agent", "verifier_agent"},
        "expected_columns": {"month", "revenue"},
        "min_rows": 1,
    },
    {
        "case_id": "golden_monthly_revenue",
        "question": "What is monthly revenue?",
        "expected_agents": {"orchestrator", "sql_agent", "visualization_agent", "verifier_agent"},
        "expected_columns": {"month", "revenue"},
        "min_rows": 1,
    },
    {
        "case_id": "golden_revenue_chart",
        "question": "Create a chart for revenue trend.",
        "expected_agents": {"orchestrator", "sql_agent", "visualization_agent", "verifier_agent"},
        "expected_columns": {"month", "revenue"},
        "min_rows": 1,
    },
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", default="dist/report")
    args = parser.parse_args()

    results = [_run_case(args.base_url.rstrip("/"), case) for case in GOLDEN_CASES]
    passed = sum(1 for result in results if result["passed"])
    artifact = {
        "source": "gke-staging-golden-correctness",
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
    json_path = output_dir / "gke-golden-correctness.json"
    markdown_path = output_dir / "gke-golden-correctness.md"
    json_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


def _run_case(base_url: str, case: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "request_id": f"req_{case['case_id']}",
        "session_id": "ses_gke_golden",
        "user_id": "u_gke_golden",
        "role": "business_user",
        "locale": "en",
        "question": case["question"],
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

    table = response_data.get("table_result")
    table_dict = _mapping(table)
    columns = {str(column) for column in _list(table_dict.get("columns"))}
    rows = _list(table_dict.get("rows"))
    agent_timeline = [
        _mapping(cast(object, item))
        for item in _list(response_data.get("agent_timeline"))
        if isinstance(item, Mapping)
    ]
    agents = {
        str(item.get("agent_name"))
        for item in agent_timeline
        if item.get("status") == "succeeded"
    }
    expected_agents = case["expected_agents"]
    expected_columns = case["expected_columns"]
    passed = (
        status_code == 200
        and expected_agents.issubset(agents)
        and expected_columns.issubset(columns)
        and len(rows) >= int(case["min_rows"])
        and bool(response_data.get("answer_text"))
    )
    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "passed": passed,
        "status_code": status_code,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 4),
        "confidence": float(response_data.get("confidence", 0.0)),
        "actual_columns": sorted(columns),
        "row_count": len(rows),
        "succeeded_agents": sorted(str(agent) for agent in agents),
        "error": error,
    }


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
        "# GKE Golden Correctness",
        "",
        f"- Base URL: {artifact['base_url']}",
        f"- Correctness rate: {artifact['correctness_rate']}",
        f"- Average confidence: {artifact['average_confidence']}",
        "",
        "| Case | Passed | Status | Confidence | Rows | Latency ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in artifact["results"]:
        lines.append(
            f"| {result['case_id']} | {result['passed']} | {result['status_code']} | "
            f"{result['confidence']} | {result['row_count']} | {result['latency_ms']} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
