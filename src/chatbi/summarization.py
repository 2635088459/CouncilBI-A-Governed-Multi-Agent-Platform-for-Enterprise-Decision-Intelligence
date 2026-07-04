"""Safe LLM-backed answer summarization with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.core.contracts import ErrorCode, WarningMessage
from chatbi.llm.types import LLMClient, LLMProviderError, LLMRequest, LLMTimeoutError


@dataclass(frozen=True, slots=True)
class SummaryGenerationResult:
    summary_text: str
    degraded: bool
    warning: WarningMessage | None = None
    provider: str | None = None
    model_name: str | None = None


class SafeSummaryGenerator:
    """Generate answer summaries without letting provider failures escape."""

    def __init__(self, llm_client: LLMClient, fallback_max_chars: int = 240) -> None:
        if fallback_max_chars <= 0:
            raise ValueError("fallback_max_chars must be greater than 0")
        self._llm_client = llm_client
        self._fallback_max_chars = fallback_max_chars

    def summarize(
        self,
        *,
        answer_text: str,
        user_id: str,
        org_id: str,
        trace_id: str,
    ) -> SummaryGenerationResult:
        request = LLMRequest(
            task_type="answer_summary",
            prompt_version="answer_summary.v1",
            messages=(
                {
                    "role": "system",
                    "content": "Summarize the analytics answer for an executive reader.",
                },
                {"role": "user", "content": answer_text},
            ),
            model_policy={"safe_fallback_required": True},
            temperature=0.0,
            max_tokens=128,
            user_id=user_id,
            org_id=org_id,
            trace_id=trace_id,
        )
        try:
            response = self._llm_client.complete(request)
        except LLMProviderError as exc:
            error_code = (
                ErrorCode.LLM_PROVIDER_TIMEOUT
                if isinstance(exc, LLMTimeoutError)
                else ErrorCode.LLM_PROVIDER_FAILURE
            )
            return SummaryGenerationResult(
                summary_text=self._fallback_summary(answer_text),
                degraded=True,
                warning=WarningMessage(
                    code=error_code,
                    message="answer_summary: Provider failed safely; fallback summary returned.",
                ),
            )

        return SummaryGenerationResult(
            summary_text=response.text,
            degraded=False,
            provider=response.provider,
            model_name=response.model_name,
        )

    def _fallback_summary(self, answer_text: str) -> str:
        normalized = " ".join(answer_text.split())
        if len(normalized) <= self._fallback_max_chars:
            return normalized
        excerpt = normalized[: self._fallback_max_chars - 3].rstrip()
        word_boundary = excerpt.rfind(" ")
        if word_boundary > 0:
            excerpt = excerpt[:word_boundary]
        return f"{excerpt}..."
