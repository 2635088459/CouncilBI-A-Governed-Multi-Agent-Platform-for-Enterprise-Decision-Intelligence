import pytest

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendApiClient, FrontendUserContext
from chatbi.frontend.fixture_transport import FixtureJsonTransport


def test_fixture_transport_drives_chat_query_without_backend() -> None:
    transport = FixtureJsonTransport()
    client = FrontendApiClient(transport)

    result = client.submit_question(
        context=_context(),
        question="Show revenue trend.",
    )

    assert result.trace_id == "trc_fixture_success"
    assert result.answer.text == "Revenue trend is ready."
    assert result.table is not None
    assert result.chart is not None
    assert transport.last_request is not None
    assert transport.last_request.method == "POST"
    assert transport.last_request.path == "/api/v1/chat/query"


def test_fixture_transport_drives_history_catalog_and_task_status() -> None:
    transport = FixtureJsonTransport()
    client = FrontendApiClient(transport)

    history = client.load_history(context=_context())
    catalog = client.load_metric_catalog(context=_context())
    status = client.load_task_status(context=_context(), task_id="task_fixture")

    assert history.items[0]["trace_id"] == "trc_fixture_success"
    assert catalog.metrics[0]["name"] == "revenue"
    assert status.status.value == "completed"
    assert status.result["chunk_count"] == 2


def test_fixture_transport_rejects_unknown_route() -> None:
    transport = FixtureJsonTransport()

    with pytest.raises(ValueError, match="No frontend API fixture"):
        transport.get_json(
            path="/api/v1/unknown",
            headers={},
            query=None,
        )


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )
