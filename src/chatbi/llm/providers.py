"""LLM provider adapters for the provider gateway."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from chatbi.llm.types import (
    LLMConfigurationError,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    ModelRoute,
    estimate_cost,
    token_count_from_messages,
)


@dataclass(slots=True)
class MockLLMProvider:
    """Deterministic, network-free provider for CI and local tests."""

    provider_name: str = "mock"
    fixed_latency_ms: int = 1
    fail_tasks: tuple[str, ...] = ()
    response_prefix: str = "mock"

    def complete(self, request: LLMRequest, route: ModelRoute) -> LLMResponse:
        if request.task_type in self.fail_tasks:
            raise LLMProviderError("Provider call failed safely.")
        prompt_tokens = token_count_from_messages(request.messages)
        generated = self._text_for(request)
        completion_tokens = max(1, len(generated.split()))
        return LLMResponse(
            text=generated,
            model_name=route.model_name,
            provider=self.provider_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost=estimate_cost(prompt_tokens, completion_tokens, route),
            latency_ms=self.fixed_latency_ms,
            finish_reason="stop",
            safety_flags=(),
        )

    def _text_for(self, request: LLMRequest) -> str:
        if request.task_type == "sql_generation":
            # Keyed off the user's actual question only, not the full
            # joined message list — the system prompt now describes the
            # real schema (simple_orchestrator.py's _SQL_GENERATION_SYSTEM_PROMPT),
            # which itself always contains "support_ticket_summary", so
            # joining it in here would make this branch fire for every
            # question, not just ticket-related ones.
            content = self._last_user_content(request).lower()
            if "support" in content or "ticket" in content:
                return (
                    "SELECT month, product, severity, ticket_count, avg_resolution_hours "
                    "FROM support_ticket_summary ORDER BY ticket_count DESC LIMIT 100"
                )
            return "SELECT month, revenue FROM revenue_by_month LIMIT 100"
        if request.task_type == "answer_synthesis":
            user_content = self._last_user_content(request)
            synthesized_support_answer = self._synthesized_support_answer(user_content)
            if synthesized_support_answer is not None:
                return synthesized_support_answer
            synthesized_revenue_answer = self._synthesized_revenue_answer(user_content)
            if synthesized_revenue_answer is not None:
                return synthesized_revenue_answer
            synthesized_evidence_answer = self._synthesized_evidence_answer(user_content)
            if synthesized_evidence_answer is not None:
                return synthesized_evidence_answer
            return "Revenue trend is ready."
        if request.task_type == "intent_classification":
            content = " ".join(message.get("content", "") for message in request.messages).lower()
            if any(word in content for word in ("why", "reason", "explain")):
                return "rag_explanation"
            if any(word in content for word in ("chart", "plot", "trend")):
                return "chart"
            if any(word in content for word in ("forecast", "predict", "anomaly")):
                return "analytics"
            return "sql_query"
        return f"{self.response_prefix}:{request.task_type}:{request.prompt_version}"

    def _last_user_content(self, request: LLMRequest) -> str:
        for message in reversed(request.messages):
            if message.get("role") == "user":
                return message.get("content", "")
        return " ".join(message.get("content", "") for message in request.messages)

    def _answer_context(self, content: str) -> dict[str, object] | None:
        try:
            context = json.loads(content)
        except json.JSONDecodeError:
            return None
        return context if isinstance(context, dict) else None

    def _synthesized_revenue_answer(self, content: str) -> str | None:
        context = self._answer_context(content)
        if context is None:
            return None

        question = str(context.get("question", "")).lower()
        if not any(word in question for word in ("highest", "largest", "max")):
            return None

        table_result = context.get("table_result", {})
        if not isinstance(table_result, dict):
            return None
        rows = table_result.get("rows", ())
        if not isinstance(rows, list):
            return None

        revenue_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("month"), str)
            and isinstance(row.get("revenue"), (int, float))
        ]
        if not revenue_rows:
            return None

        highest = max(revenue_rows, key=lambda row: float(row["revenue"]))
        return (
            f"Highest revenue month was {highest['month']} with revenue "
            f"{float(highest['revenue'])}, based on the provided SQL rows."
        )

    def _synthesized_support_answer(self, content: str) -> str | None:
        context = self._answer_context(content)
        if context is None:
            return None

        table_result = context.get("table_result", {})
        if not isinstance(table_result, dict):
            return None
        columns = table_result.get("columns", ())
        rows = table_result.get("rows", ())
        if not isinstance(columns, list) or not isinstance(rows, list):
            return None
        if "ticket_count" not in columns or not rows:
            return None
        first = rows[0]
        if not isinstance(first, dict):
            return None
        product = first.get("product", "the leading product area")
        severity = first.get("severity", "priority")
        return (
            f"Support ticket volume is led by {product} {severity} tickets, "
            "grounded in the provided SQL rows and support operations evidence."
        )

    def _synthesized_evidence_answer(self, content: str) -> str | None:
        context = self._answer_context(content)
        if context is None:
            return None

        question = str(context.get("question", "")).lower()
        if not any(word in question for word in ("why", "explain", "reason")):
            return None

        evidence_list = context.get("evidence_list", ())
        if not isinstance(evidence_list, list) or not evidence_list:
            return None

        first = evidence_list[0]
        if not isinstance(first, dict):
            return None
        anchor = str(first.get("citation_anchor", "provided evidence"))
        snippet = str(first.get("snippet", "")).strip()
        if not snippet:
            return None
        return f"Revenue changed based on evidence from {anchor}: {snippet}"


class OpenAIChatProvider:
    """Minimal OpenAI-compatible chat adapter using stdlib HTTP.

    The adapter intentionally has no SDK dependency. It is suitable for the
    optional smoke test and keeps baseline tests network-free.
    """

    provider_name = "openai"

    def __init__(
        self,
        api_key_env: str = "OPENAI_API_KEY",
        base_url_env: str = "OPENAI_BASE_URL",
    ) -> None:
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise LLMConfigurationError(f"{api_key_env} is required for OpenAIChatProvider")
        self._api_key = api_key
        self._base_url = os.getenv(base_url_env) or "https://api.openai.com/v1"

    def complete(self, request: LLMRequest, route: ModelRoute) -> LLMResponse:
        started = time.perf_counter()
        payload = {
            "model": route.model_name,
            "messages": list(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        http_request = urllib.request.Request(
            f"{self._base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request,
                timeout=route.timeout_ms / 1000.0,
            ) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMProviderError("Provider call failed safely.") from exc

        parsed = json.loads(raw)
        choice = parsed.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = parsed.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        return LLMResponse(
            text=str(message.get("content", "")),
            model_name=str(parsed.get("model", route.model_name)),
            provider=self.provider_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost=estimate_cost(prompt_tokens, completion_tokens, route),
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
            finish_reason=str(choice.get("finish_reason", "unknown")),
            safety_flags=(),
            raw_response_ref=str(parsed.get("id", "")) or None,
        )
