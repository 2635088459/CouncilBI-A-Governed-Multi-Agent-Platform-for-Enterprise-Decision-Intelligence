from chatbi.core.contracts import ChartType
from chatbi.frontend.ui_answer_state import (
    UiAnswerStatus,
    answer_state_as_dict,
    answer_state_from_result,
    failed_answer_state,
    idle_answer_state,
    running_answer_state,
    submitting_answer_state,
)
from chatbi.frontend.view_models import (
    ChartCardViewModel,
    EvidenceCardViewModel,
    MessageBubbleViewModel,
    MessageRole,
    QueryResultViewModel,
    SqlExplainCardViewModel,
    TableCardViewModel,
    WarningBannerViewModel,
)


def test_idle_submitting_and_running_states_match_spec_fields() -> None:
    idle = idle_answer_state()
    submitting = submitting_answer_state()
    running = running_answer_state(trace_id="trc_running")

    assert answer_state_as_dict(idle) == {
        "status": "idle",
        "trace_id": None,
        "answer_text": None,
        "table_result": None,
        "chart_spec": None,
        "evidence_list": [],
        "warnings": [],
        "error_code": None,
    }
    assert submitting.status is UiAnswerStatus.SUBMITTING
    assert submitting.has_visible_result is False
    assert running.status is UiAnswerStatus.RUNNING
    assert running.trace_id == "trc_running"


def test_completed_answer_state_keeps_renderable_answer_payload() -> None:
    state = answer_state_from_result(_result())

    assert state.status is UiAnswerStatus.COMPLETED
    assert state.trace_id == "trc_answer"
    assert state.answer_text == "Revenue trend is ready."
    assert state.table_result == {
        "columns": ["order_month", "revenue"],
        "rows": [{"order_month": "2026-06", "revenue": 1200}],
    }
    assert state.chart_spec == {
        "chart_type": "line",
        "x_field": "order_month",
        "y_fields": ["revenue"],
        "title": "Revenue Trend",
    }
    assert state.evidence_list[0]["source_id"] == "doc_001"
    assert state.error_code is None
    assert state.has_visible_result is True


def test_partial_failure_answer_state_keeps_table_and_chart_visible() -> None:
    result = _result(
        warnings=(
            WarningBannerViewModel(
                code="AGENT_PARTIAL_FAILURE",
                message="Visualization agent failed.",
                is_partial_failure=True,
            ),
        )
    )

    state = answer_state_from_result(result)

    assert state.status is UiAnswerStatus.PARTIAL
    assert state.table_result is not None
    assert state.chart_spec is not None
    assert state.warnings[0]["code"] == "AGENT_PARTIAL_FAILURE"
    assert state.error_code is None


def test_failed_answer_state_uses_error_code_without_result_payload() -> None:
    state = failed_answer_state(
        error_code="SQL_GUARDRAIL_DENIED",
        message="Only read-only SELECT queries are allowed.",
        trace_id="trc_denied",
    )

    assert state.status is UiAnswerStatus.FAILED
    assert state.trace_id == "trc_denied"
    assert state.answer_text is None
    assert state.table_result is None
    assert state.chart_spec is None
    assert state.error_code == "SQL_GUARDRAIL_DENIED"
    assert state.warnings == [
        {
            "code": "SQL_GUARDRAIL_DENIED",
            "message": "Only read-only SELECT queries are allowed.",
        }
    ]
    assert state.has_visible_result is False


def _result(
    warnings: tuple[WarningBannerViewModel, ...] = (),
) -> QueryResultViewModel:
    return QueryResultViewModel(
        trace_id="trc_answer",
        answer=MessageBubbleViewModel(
            role=MessageRole.ASSISTANT,
            text="Revenue trend is ready.",
            trace_id="trc_answer",
        ),
        warnings=warnings,
        table=TableCardViewModel(
            columns=("order_month", "revenue"),
            rows=({"order_month": "2026-06", "revenue": 1200},),
        ),
        chart=ChartCardViewModel(
            chart_type=ChartType.LINE,
            x_field="order_month",
            y_fields=("revenue",),
            title="Revenue Trend",
        ),
        analytics=None,
        evidence=(
            EvidenceCardViewModel(
                source_id="doc_001",
                title="Revenue Review",
                citation_anchor="p3",
                snippet="Revenue increased after the campaign.",
            ),
        ),
        sql_explain=SqlExplainCardViewModel(
            sql_text="SELECT order_month, revenue FROM monthly_revenue",
            explanation="Generated SQL used by the governed query pipeline.",
        ),
        confidence=0.92,
    )
