"""GroundedAnswerSynthesizer, including Spec FV10.4's conversation_context
and Spec FV10.12's extra_instructions (10-followups/12)."""

from dataclasses import dataclass, field

from chatbi.answer_synthesis import GroundedAnswerSynthesizer
from chatbi.core.contracts import TableResult
from chatbi.llm.types import LLMRequest, LLMResponse


def _empty_requests() -> list[LLMRequest]:
    return []


@dataclass(slots=True)
class _RecordingLLMClient:
    response_text: str = "Synthesized answer."
    requests_seen: list[LLMRequest] = field(default_factory=_empty_requests)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests_seen.append(request)
        return LLMResponse(
            text=self.response_text,
            model_name="mock-model",
            provider="mock",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            estimated_cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )


def _table_result() -> TableResult:
    return TableResult(columns=("month", "revenue"), rows=({"month": "2026-07", "revenue": 900.0},))


def test_synthesize_without_conversation_context_sends_only_system_and_user_messages() -> None:
    llm_client = _RecordingLLMClient()
    synthesizer = GroundedAnswerSynthesizer(llm_client)

    synthesizer.synthesize(
        question="What was July revenue?",
        safe_sql="SELECT month, revenue FROM revenue_by_month",
        table_result=_table_result(),
        evidence_list=(),
        user_id="u_001",
        org_id="org_1",
        trace_id="trc_1",
    )

    assert len(llm_client.requests_seen) == 1
    assert len(llm_client.requests_seen[0].messages) == 2


def test_synthesize_prepends_conversation_context_before_the_current_question() -> None:
    # Spec FV10.4 FR-FV10-052/056
    llm_client = _RecordingLLMClient()
    synthesizer = GroundedAnswerSynthesizer(llm_client)

    synthesizer.synthesize(
        question="What about the month before that?",
        safe_sql="SELECT month, revenue FROM revenue_by_month",
        table_result=_table_result(),
        evidence_list=(),
        user_id="u_001",
        org_id="org_1",
        trace_id="trc_2",
        conversation_context=(
            {"role": "user", "content": "What was July revenue?"},
            {"role": "assistant", "content": "July revenue was 900."},
        ),
    )

    assert len(llm_client.requests_seen) == 1
    messages = llm_client.requests_seen[0].messages
    assert len(messages) == 4
    assert messages[1] == {"role": "user", "content": "What was July revenue?"}
    assert messages[2] == {"role": "assistant", "content": "July revenue was 900."}
    assert "What about the month before that?" in messages[3]["content"]


def test_synthesize_appends_extra_instructions_to_the_system_message() -> None:
    llm_client = _RecordingLLMClient()
    synthesizer = GroundedAnswerSynthesizer(llm_client)

    synthesizer.synthesize(
        question="Flag regions with more than 5% variance.",
        safe_sql="SELECT * FROM db_revenue d JOIN file_x f ON d.region = f.region",
        table_result=TableResult(columns=("region",), rows=()),
        evidence_list=(),
        user_id="u_001",
        org_id="org_1",
        trace_id="trc_3",
        extra_instructions="Do not claim this means all values are within any threshold.",
    )

    assert len(llm_client.requests_seen) == 1
    system_message = llm_client.requests_seen[0].messages[0]
    assert "Do not claim this means all values are within any threshold." in system_message["content"]


def test_synthesize_without_extra_instructions_does_not_alter_the_system_message() -> None:
    llm_client = _RecordingLLMClient()
    synthesizer = GroundedAnswerSynthesizer(llm_client)

    synthesizer.synthesize(
        question="What was July revenue?",
        safe_sql="SELECT month, revenue FROM revenue_by_month",
        table_result=_table_result(),
        evidence_list=(),
        user_id="u_001",
        org_id="org_1",
        trace_id="trc_4",
    )

    system_message = llm_client.requests_seen[0].messages[0]
    assert system_message["content"] == (
        "You are a governed enterprise ChatBI analyst. Answer only from the "
        "provided SQL result rows and evidence snippets. If the context is "
        "insufficient, say what is missing. Cite evidence anchors when useful. "
        "Prior turns in this conversation (if any) may precede this message — "
        "read them to resolve pronouns or references in the current question."
    )


def test_fallback_answer_states_no_matching_rows_when_extra_instructions_and_empty_table() -> None:
    # No llm_client at all exercises the deterministic fallback path
    # directly — this must not fall through to a generic "ready" message
    # that reads as a confirmed result for a flagged join mismatch.
    synthesizer = GroundedAnswerSynthesizer(llm_client=None)

    result = synthesizer.synthesize(
        question="Flag regions with more than 5% variance.",
        safe_sql="SELECT * FROM db_revenue d JOIN file_x f ON d.region = f.region",
        table_result=TableResult(columns=("region",), rows=()),
        evidence_list=(),
        user_id="u_001",
        org_id="org_1",
        trace_id="trc_5",
        extra_instructions="Do not claim this means all values are within any threshold.",
    )

    assert "No matching records were found across the join key" in result.answer_text
