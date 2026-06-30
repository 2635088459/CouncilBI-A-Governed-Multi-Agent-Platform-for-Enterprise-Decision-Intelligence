import pytest

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import parse_api_envelope
from chatbi.frontend.api_fixtures import (
    FrontendApiFixture,
    all_frontend_api_fixtures,
    partial_failure_chat_query_fixture,
    sql_guardrail_denied_fixture,
    successful_chat_query_fixture,
    task_status_completed_fixture,
)
from chatbi.frontend.api_client import FrontendUserContext
from chatbi.frontend.component_props import build_chat_page_props
from chatbi.frontend.chat_state import ChatPageState
from chatbi.frontend.task_status_state import (
    UiTaskStatus,
    build_task_status_view_model,
)
from chatbi.frontend.ui_answer_state import (
    UiAnswerStatus,
    answer_state_from_result,
    failed_answer_state,
)
from chatbi.frontend.view_models import build_query_result_view_model


def test_successful_chat_fixture_builds_renderable_answer_state() -> None:
    parsed = parse_api_envelope(successful_chat_query_fixture().response)
    result = build_query_result_view_model(parsed.as_mapping())
    answer_state = answer_state_from_result(result)

    assert answer_state.status is UiAnswerStatus.COMPLETED
    assert answer_state.answer_text == "Revenue trend is ready."
    assert answer_state.table_result is not None
    assert answer_state.chart_spec is not None
    assert answer_state.evidence_list[0]["source_id"] == "doc_001"


def test_partial_failure_fixture_keeps_available_data_visible() -> None:
    parsed = parse_api_envelope(partial_failure_chat_query_fixture().response)
    result = build_query_result_view_model(parsed.as_mapping())
    answer_state = answer_state_from_result(result)

    assert answer_state.status is UiAnswerStatus.PARTIAL
    assert answer_state.table_result is not None
    assert answer_state.chart_spec is not None
    assert answer_state.warnings[0]["code"] == "AGENT_PARTIAL_FAILURE"


def test_sql_denial_fixture_builds_user_actionable_error_boundary() -> None:
    parsed = parse_api_envelope(sql_guardrail_denied_fixture().response)
    assert parsed.error is not None

    answer_state = failed_answer_state(
        error_code=parsed.error.code,
        message=parsed.error.message,
        trace_id=parsed.trace_id,
    )
    props = build_chat_page_props(
        ChatPageState(context=_context(), answer_state=answer_state),
        Locale.EN,
    )

    assert props.error_boundary is not None
    assert props.error_boundary.title == "Query blocked for safety"
    assert "narrower business metric" in props.error_boundary.message
    assert props.trace is not None
    assert props.trace.copy_value == "trc_fixture_denied"


def test_task_status_fixture_builds_completed_task_view_model() -> None:
    parsed = parse_api_envelope(task_status_completed_fixture().response)
    assert parsed.data is not None

    status = build_task_status_view_model(parsed.data, Locale.EN)

    assert status.task_id == "task_fixture"
    assert status.status is UiTaskStatus.COMPLETED
    assert status.label == "Completed"
    assert status.result["chunk_count"] == 2


@pytest.mark.parametrize("fixture", all_frontend_api_fixtures())
def test_all_frontend_api_fixtures_use_v2_envelope_shape(
    fixture: FrontendApiFixture,
) -> None:
    parsed = parse_api_envelope(fixture.response)

    assert fixture.path.startswith("/api/v1/")
    assert fixture.method in {"GET", "POST"}
    assert parsed.request_id.startswith("req_")
    assert parsed.trace_id is not None


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )
