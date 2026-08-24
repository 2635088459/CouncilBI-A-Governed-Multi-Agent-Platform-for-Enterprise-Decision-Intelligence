"""Estimate token savings from governed SQL/RAG context reduction."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from chatbi.llm.types import token_count_from_messages


SQL_SYSTEM_PROMPT = (
    "You are a DuckDB/Postgres-compatible SQL generator for the governed "
    "ChatBI schema. Reply with exactly one read-only SQL statement and nothing else.\n\n"
    "Available tables:\n"
    "revenue_by_month(month VARCHAR, revenue NUMERIC)\n"
    "support_ticket_summary(month VARCHAR, product VARCHAR, severity VARCHAR, "
    "ticket_count INTEGER, avg_resolution_hours NUMERIC)"
)

ANSWER_SYSTEM_PROMPT = (
    "You are a governed enterprise ChatBI analyst. Answer only from the provided "
    "SQL result rows and evidence snippets. If the context is insufficient, say "
    "what is missing. Cite evidence anchors when useful."
)

QUESTIONS = (
    (
        "For the July 2026 revenue drop, quantify the shortfall versus June and "
        "forecast, identify the most likely root causes across campaign and support "
        "evidence, and recommend two mitigations for Q4 planning."
    ),
    (
        "Prepare an executive risk narrative that connects Q2 revenue growth, July "
        "campaign suspension, support-ticket severity, SLA breaches, and churn risk. "
        "Use numbers, cite evidence, and separate confirmed facts from uncertainty."
    ),
    (
        "Which product areas need leadership attention before the next board meeting? "
        "Rank products by support-ticket load and resolution time, then connect the "
        "ranking to incident reports, retention risk, and likely revenue impact."
    ),
    (
        "Investigate whether marketing concentration created a measurable business "
        "continuity risk. Compare campaign-attributed revenue, July revenue decline, "
        "recovery trajectory, and documented partner-review delays."
    ),
    (
        "Explain whether the Analytics Hub timeout incident is an isolated reliability "
        "issue or part of a recurring operational pattern. Use support, incident, "
        "release-note, and revenue evidence."
    ),
    (
        "Draft a data-backed customer-retention brief: identify churn drivers, affected "
        "segments, product gaps, support/SLA contributors, and the operating metrics "
        "management should monitor next month."
    ),
)


def main() -> None:
    output_dir = Path("dist/report")
    output_dir.mkdir(parents=True, exist_ok=True)

    full_context = _full_enterprise_context()
    optimized_cases = [_optimized_case(question) for question in QUESTIONS]
    naive_cases = [_naive_case(question, full_context) for question in QUESTIONS]
    rows = [
        _comparison_row(question, optimized, naive)
        for question, optimized, naive in zip(QUESTIONS, optimized_cases, naive_cases, strict=True)
    ]
    optimized_total = sum(row["optimized_total_tokens"] for row in rows)
    naive_total = sum(row["naive_total_tokens"] for row in rows)
    artifact = {
        "source": "local-token-estimation",
        "tokenizer_note": (
            "Uses the repository's provider-neutral word-count token estimator. "
            "Use OpenAI usage fields for exact production billing tokens."
        ),
        "case_count": len(rows),
        "optimized_total_tokens": optimized_total,
        "naive_total_tokens": naive_total,
        "tokens_saved": naive_total - optimized_total,
        "token_reduction_rate": round((naive_total - optimized_total) / naive_total, 4),
        "average_optimized_tokens": round(statistics.fmean(row["optimized_total_tokens"] for row in rows), 4),
        "average_naive_tokens": round(statistics.fmean(row["naive_total_tokens"] for row in rows), 4),
        "average_tokens_saved_per_question": round(
            statistics.fmean(row["tokens_saved"] for row in rows),
            4,
        ),
        "cases": rows,
    }

    json_path = output_dir / "token-savings-report.json"
    markdown_path = output_dir / "token-savings-report.md"
    json_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


def _optimized_case(question: str) -> dict[str, int]:
    sql_messages = (
        {"role": "system", "content": SQL_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    )
    answer_messages = (
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "safe_sql": _safe_sql_for(question),
                    "table_result": {
                        "columns": _columns_for(question),
                        "rows": _bounded_rows_for(question),
                        "returned_row_count": len(_bounded_rows_for(question)),
                    },
                    "evidence_list": _top_evidence_for(question),
                },
                ensure_ascii=True,
            ),
        },
    )
    return {
        "sql_generation_prompt_tokens": token_count_from_messages(sql_messages),
        "answer_synthesis_prompt_tokens": token_count_from_messages(answer_messages),
        "completion_budget_tokens": 256 + 512,
    }


def _naive_case(question: str, full_context: str) -> dict[str, int]:
    messages = (
        {
            "role": "system",
            "content": (
                "You are an enterprise analyst. Answer the question using all "
                "available database rows and documents included by the user."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "full_database_and_document_context": full_context,
                },
                ensure_ascii=True,
            ),
        },
    )
    return {
        "single_prompt_tokens": token_count_from_messages(messages),
        "completion_budget_tokens": 768,
    }


def _comparison_row(question: str, optimized: dict[str, int], naive: dict[str, int]) -> dict[str, Any]:
    optimized_total = (
        optimized["sql_generation_prompt_tokens"]
        + optimized["answer_synthesis_prompt_tokens"]
        + optimized["completion_budget_tokens"]
    )
    naive_total = naive["single_prompt_tokens"] + naive["completion_budget_tokens"]
    return {
        "question": question,
        "optimized_prompt_tokens": optimized["sql_generation_prompt_tokens"]
        + optimized["answer_synthesis_prompt_tokens"],
        "optimized_total_tokens": optimized_total,
        "naive_prompt_tokens": naive["single_prompt_tokens"],
        "naive_total_tokens": naive_total,
        "tokens_saved": naive_total - optimized_total,
        "reduction_rate": round((naive_total - optimized_total) / naive_total, 4),
    }


def _safe_sql_for(question: str) -> str:
    normalized = question.lower()
    if "campaign" in normalized or "marketing" in normalized:
        return (
            "WITH campaign_roi AS ("
            "SELECT month, channel, SUM(spend) AS spend, SUM(attributed_revenue) AS revenue "
            "FROM marketing_campaigns GROUP BY month, channel"
            ") SELECT month, channel, spend, revenue, revenue / NULLIF(spend, 0) AS roi "
            "FROM campaign_roi ORDER BY month, revenue DESC LIMIT 100"
        )
    if "support" in normalized or "product" in normalized or "sla" in normalized:
        return (
            "SELECT month, product, severity, ticket_count, avg_resolution_hours "
            "FROM support_ticket_summary ORDER BY ticket_count DESC LIMIT 100"
        )
    return (
        "SELECT month, revenue, "
        "revenue - LAG(revenue) OVER (ORDER BY month) AS month_over_month_change "
        "FROM revenue_by_month ORDER BY month LIMIT 100"
    )


def _columns_for(question: str) -> list[str]:
    normalized = question.lower()
    if "campaign" in normalized or "marketing" in normalized:
        return ["month", "channel", "spend", "revenue", "roi"]
    if "support" in normalized or "product" in normalized or "sla" in normalized:
        return ["month", "product", "severity", "ticket_count", "avg_resolution_hours"]
    return ["month", "revenue", "month_over_month_change"]


def _bounded_rows_for(question: str) -> list[dict[str, Any]]:
    normalized = question.lower()
    if "campaign" in normalized or "marketing" in normalized:
        return [
            {"month": "2026-06", "channel": "paid_search", "spend": 182000, "revenue": 501000, "roi": 2.75},
            {"month": "2026-06", "channel": "social", "spend": 96000, "revenue": 259000, "roi": 2.7},
            {"month": "2026-07", "channel": "paid_search", "spend": 41000, "revenue": 98000, "roi": 2.39},
            {"month": "2026-07", "channel": "social", "spend": 23000, "revenue": 52000, "roi": 2.26},
            {"month": "2026-08", "channel": "paid_search", "spend": 94000, "revenue": 251000, "roi": 2.67},
            {"month": "2026-09", "channel": "paid_search", "spend": 112000, "revenue": 318000, "roi": 2.84},
        ]
    if "support" in normalized or "product" in normalized or "sla" in normalized:
        return [
            {
                "month": f"2026-{month:02d}",
                "product": product,
                "severity": severity,
                "ticket_count": 42 + month,
                "avg_resolution_hours": round(7.5 + month * 0.2, 2),
            }
            for month, product, severity in (
                (1, "Analytics Hub", "P1"),
                (2, "Billing", "P2"),
                (3, "Data API", "P1"),
                (4, "Analytics Hub", "P2"),
                (5, "Mobile", "P3"),
                (6, "Data API", "P2"),
            )
        ]
    return [
        {"month": "2026-04", "revenue": 1210000, "month_over_month_change": 180000},
        {"month": "2026-05", "revenue": 1290000, "month_over_month_change": 80000},
        {"month": "2026-06", "revenue": 1350000, "month_over_month_change": 60000},
        {"month": "2026-07", "revenue": 890000, "month_over_month_change": -460000},
        {"month": "2026-08", "revenue": 1050000, "month_over_month_change": 160000},
        {"month": "2026-09", "revenue": 1185000, "month_over_month_change": 135000},
    ]


def _top_evidence_for(question: str) -> list[dict[str, Any]]:
    normalized = question.lower()
    evidence = [
        {
            "source_id": "doc_revenue_ops",
            "title": "July 2026 Revenue Incident",
            "citation_anchor": "revenue.incident#2026-07",
            "snippet": (
                "July 2026 revenue was $890,000, down 34.1% versus June and "
                "$293,000 below forecast after a 21-day Summer Sale campaign suspension."
            ),
            "relevance_score": 0.94,
        }
    ]
    if any(term in normalized for term in ("campaign", "marketing", "july", "revenue")):
        evidence.append(
            {
                "source_id": "doc_campaign_ops",
                "title": "Campaign Concentration Review",
                "citation_anchor": "campaign.ops#2026-07",
                "snippet": (
                    "68% of July revenue plan depended on two paid campaigns; "
                    "TrafficGuard re-review backlog averaged 13 days."
                ),
                "relevance_score": 0.92,
            }
        )
    if any(term in normalized for term in ("support", "sla", "product", "timeout", "reliability")):
        evidence.append(
            {
                "source_id": "doc_support_ops",
                "title": "Support Operations Review",
                "citation_anchor": "support.ops#2026-07",
                "snippet": (
                    "Analytics Hub query engine timeouts affected 15% of executions; "
                    "33 high-severity tickets opened over five days."
                ),
                "relevance_score": 0.91,
            }
        )
    if any(term in normalized for term in ("churn", "retention", "customer")):
        evidence.append(
            {
                "source_id": "doc_churn",
                "title": "H1 2026 Customer Churn Analysis",
                "citation_anchor": "retention.churn#2026-h1",
                "snippet": (
                    "H1 churn was 3.2% versus a 2.5% target; 29% of churned customers "
                    "cited ML Pipeline integration complexity."
                ),
                "relevance_score": 0.9,
            }
        )
    return evidence[:4]


def _full_enterprise_context() -> str:
    revenue_rows = [
        {
            "month": f"{year}-{month:02d}",
            "revenue": 640000 + (year - 2023) * 130000 + month * 38000,
            "forecast": 700000 + (year - 2023) * 135000 + month * 41000,
            "region": region,
        }
        for year in range(2023, 2027)
        for month in range(1, 13)
        for region in ("NA", "EMEA", "APAC")
    ]
    support_rows = [
        {
            "month": f"{year}-{month:02d}",
            "product": product,
            "severity": severity,
            "ticket_count": 20 + month + index + (year - 2023) * 3,
            "avg_resolution_hours": round(4.0 + month * 0.3 + index * 0.1 + (year - 2023) * 0.4, 2),
            "sla_met_rate": round(0.99 - index * 0.015 - month * 0.002, 3),
        }
        for year in range(2023, 2027)
        for month in range(1, 13)
        for index, (product, severity) in enumerate(
            (
                ("Analytics Hub", "P1"),
                ("Analytics Hub", "P2"),
                ("Billing", "P2"),
                ("Data API", "P1"),
                ("Mobile", "P3"),
            )
        )
    ]
    campaign_rows = [
        {
            "campaign_id": f"cmp_{year}_{month:02d}_{index}",
            "month": f"{year}-{month:02d}",
            "channel": channel,
            "spend": 25000 + month * 3000 + index * 7000,
            "impressions": 500000 + month * 25000 + index * 80000,
            "clicks": 12000 + month * 700 + index * 2000,
            "conversions": 280 + month * 16 + index * 55,
            "attributed_revenue": 70000 + month * 9000 + index * 26000,
            "status": "paused" if year == 2026 and month == 7 and index in (0, 1) else "active",
        }
        for year in range(2024, 2027)
        for month in range(1, 13)
        for index, channel in enumerate(("paid_search", "social", "email", "affiliate"))
    ]
    documents = [
        {
            "title": f"Enterprise Operations Review {index}",
            "body": (
                "Revenue, customer support, campaign operations, infrastructure, "
                "governance, product adoption, churn risk, SLA performance, and "
                "incident remediation were reviewed. The document includes root-cause "
                "analysis, time-series context, customer impact, mitigation owners, "
                "executive decisions, policy exceptions, support queue details, "
                "forecast deltas, campaign ROI, and next-quarter risks. "
            )
            * 18,
        }
        for index in range(1, 61)
    ]
    return json.dumps(
        {
            "tables": {
                "revenue_by_month": revenue_rows,
                "support_ticket_summary": support_rows,
                "marketing_campaigns": campaign_rows,
            },
            "documents": documents,
        },
        ensure_ascii=True,
    )


def _render_markdown(artifact: dict[str, Any]) -> str:
    lines = [
        "# Token Savings Report",
        "",
        f"- Source: {artifact['source']}",
        f"- Case count: {artifact['case_count']}",
        f"- Optimized total tokens: {artifact['optimized_total_tokens']}",
        f"- Naive total tokens: {artifact['naive_total_tokens']}",
        f"- Tokens saved: {artifact['tokens_saved']}",
        f"- Token reduction rate: {artifact['token_reduction_rate']}",
        f"- Avg optimized tokens/question: {artifact['average_optimized_tokens']}",
        f"- Avg naive tokens/question: {artifact['average_naive_tokens']}",
        f"- Avg tokens saved/question: {artifact['average_tokens_saved_per_question']}",
        "",
        "| Question | Optimized Tokens | Naive Tokens | Tokens Saved | Reduction |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for case in artifact["cases"]:
        lines.append(
            f"| {case['question']} | {case['optimized_total_tokens']} | "
            f"{case['naive_total_tokens']} | {case['tokens_saved']} | "
            f"{case['reduction_rate']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "The optimized path uses SQL to retrieve bounded rows and RAG to pass only "
                "top evidence snippets into answer synthesis. The naive path simulates sending "
                "the full table/document context directly to the model."
            ),
            "",
            (
                "These numbers are estimator-based and are suitable for an engineering report. "
                "For exact billing, run the same cases with the OpenAI provider and record the "
                "provider-returned usage fields."
            ),
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
