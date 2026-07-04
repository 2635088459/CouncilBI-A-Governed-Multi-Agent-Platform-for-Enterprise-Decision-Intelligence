"""Grounded answer synthesis from query rows and document evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from chatbi.core.contracts import (
    ErrorCode,
    EvidenceItem,
    TableResult,
    WarningMessage,
)
from chatbi.llm import LLMClient, LLMProviderError, LLMRequest, LLMTimeoutError


@dataclass(frozen=True, slots=True)
class AnswerSynthesisResult:
    answer_text: str
    warnings: tuple[WarningMessage, ...] = ()


class GroundedAnswerSynthesizer:
    """Ask the LLM to write only from bounded SQL rows and evidence snippets."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        max_rows: int = 20,
        max_evidence_items: int = 5,
    ) -> None:
        self._llm_client = llm_client
        self._max_rows = max_rows
        self._max_evidence_items = max_evidence_items

    def synthesize(
        self,
        *,
        question: str,
        safe_sql: str,
        table_result: TableResult,
        evidence_list: tuple[EvidenceItem, ...],
        user_id: str,
        org_id: str,
        trace_id: str,
    ) -> AnswerSynthesisResult:
        if self._llm_client is None:
            return AnswerSynthesisResult(
                answer_text=self._fallback_answer(question, safe_sql, table_result, evidence_list)
            )

        request = LLMRequest(
            task_type="answer_synthesis",
            prompt_version="answer_synthesis.grounded.v1",
            messages=(
                {
                    "role": "system",
                    "content": (
                        "You are a governed enterprise ChatBI analyst. Answer only from the "
                        "provided SQL result rows and evidence snippets. If the context is "
                        "insufficient, say what is missing. Cite evidence anchors when useful."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": question,
                            "safe_sql": safe_sql,
                            "table_result": {
                                "columns": table_result.columns,
                                "rows": table_result.rows[: self._max_rows],
                                "returned_row_count": len(table_result.rows),
                            },
                            "evidence_list": [
                                {
                                    "source_id": evidence.source_id,
                                    "title": evidence.title,
                                    "citation_anchor": evidence.citation_anchor,
                                    "snippet": evidence.snippet,
                                    "relevance_score": evidence.relevance_score,
                                }
                                for evidence in evidence_list[: self._max_evidence_items]
                            ],
                        },
                        default=str,
                        ensure_ascii=True,
                    ),
                },
            ),
            model_policy={
                "grounded_only": True,
                "max_rows": self._max_rows,
                "max_evidence_items": self._max_evidence_items,
            },
            temperature=0.0,
            max_tokens=512,
            user_id=user_id,
            org_id=org_id,
            trace_id=trace_id,
        )
        try:
            response = self._llm_client.complete(request)
        except LLMTimeoutError:
            return AnswerSynthesisResult(
                answer_text=self._fallback_answer(question, safe_sql, table_result, evidence_list),
                warnings=(
                    WarningMessage(
                        code=ErrorCode.LLM_PROVIDER_TIMEOUT,
                        message="Answer synthesis timed out; returned deterministic grounded fallback.",
                    ),
                ),
            )
        except LLMProviderError:
            return AnswerSynthesisResult(
                answer_text=self._fallback_answer(question, safe_sql, table_result, evidence_list),
                warnings=(
                    WarningMessage(
                        code=ErrorCode.LLM_PROVIDER_FAILURE,
                        message="Answer synthesis provider failed; returned deterministic grounded fallback.",
                    ),
                ),
            )

        text = response.text.strip()
        if not text:
            text = self._fallback_answer(question, safe_sql, table_result, evidence_list)
        return AnswerSynthesisResult(answer_text=text)

    def _fallback_answer(
        self,
        question: str,
        safe_sql: str,
        table_result: TableResult,
        evidence_list: tuple[EvidenceItem, ...],
    ) -> str:
        normalized = f"{question} {safe_sql}".lower()
        if self._is_support_ticket_table(table_result):
            return self._support_ticket_fallback(table_result, evidence_list)
        if "highest" in normalized or "max" in normalized or "largest" in normalized:
            highest = self._highest_revenue_row(table_result)
            if highest is not None:
                month = highest.get("month")
                revenue = highest.get("revenue")
                return f"Highest revenue month was {month} with revenue {revenue}."
        if ("why" in normalized or "explain" in normalized or "reason" in normalized) and evidence_list:
            evidence = evidence_list[0]
            return f"Revenue changed based on evidence from {evidence.citation_anchor}: {evidence.snippet}"
        return "Revenue trend is ready."

    def _support_ticket_fallback(
        self,
        table_result: TableResult,
        evidence_list: tuple[EvidenceItem, ...],
    ) -> str:
        if not table_result.rows:
            return "No support ticket rows were returned for the governed query."
        first = table_result.rows[0]
        if "month" in table_result.columns and "ticket_count" in table_result.columns:
            month = first.get("month")
            count = first.get("ticket_count")
            severity = first.get("severity")
            product = first.get("product")
            evidence_suffix = (
                f" Evidence: {evidence_list[0].citation_anchor}."
                if evidence_list
                else ""
            )
            return (
                f"Support ticket volume is led by {product} {severity} tickets in {month} "
                f"with {count} tickets.{evidence_suffix}"
            )
        return f"Support ticket query returned {len(table_result.rows)} rows."

    def _is_support_ticket_table(self, table_result: TableResult) -> bool:
        return "ticket_count" in table_result.columns and (
            "product" in table_result.columns or "severity" in table_result.columns
        )

    def _highest_revenue_row(self, table_result: TableResult) -> Mapping[str, object] | None:
        if "month" not in table_result.columns or "revenue" not in table_result.columns:
            return None
        rows = [row for row in table_result.rows if isinstance(row.get("revenue"), (int, float))]
        if not rows:
            return None
        return max(rows, key=lambda row: float(row["revenue"]))
