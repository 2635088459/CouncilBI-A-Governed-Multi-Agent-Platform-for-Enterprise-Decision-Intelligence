from typing import Any, Mapping, cast

from fastapi.testclient import TestClient

from chatbi.api.http import create_app
from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendApiClient, FrontendUserContext
from chatbi.frontend.app_shell import FrontendAppShell, FrontendRoute
from chatbi.frontend.chat_state import ChatTurnStatus
from chatbi.frontend.evaluation_state import ReleaseGateStatus
from chatbi.frontend.view_models import ResultBlockType


class _TestClientJsonTransport:
    def __init__(self, client: Any) -> None:
        self._client = client

    def post_json(
        self,
        path: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        response: Any = self._client.post(
            path,
            headers=dict(headers),
            params=dict(query or {}),
            json=body,
        )
        return cast(Mapping[str, Any], response.json())

    def get_json(
        self,
        path: str,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        response: Any = self._client.get(
            path,
            headers=dict(headers),
            params=dict(query or {}),
        )
        return cast(Mapping[str, Any], response.json())


def test_frontend_app_shell_runs_against_real_backend_api() -> None:
    backend_client: Any = TestClient(create_app())
    api_client = FrontendApiClient(_TestClientJsonTransport(backend_client))
    shell = FrontendAppShell(context=_context(), api_client=api_client)

    chat_state = shell.submit_chat_question("Show revenue trend.")
    chat_props = shell.chat_props()

    assert chat_state.route is FrontendRoute.CHAT
    assert chat_state.chat.turns[0].status is ChatTurnStatus.ANSWERED
    assert chat_state.chat.turns[0].result is not None
    assert chat_state.chat.turns[0].result.answer.text == "Revenue trend is ready."
    assert chat_props.turns[0].result is not None
    assert chat_props.turns[0].result.answer_text == "Revenue trend is ready."

    history_state = shell.load_history()
    history_item = history_state.history.items[0]

    assert history_state.route is FrontendRoute.HISTORY
    assert history_item.question == "Show revenue trend."
    assert history_item.can_replay is True

    shell.select_history_for_replay(history_item.trace_id)
    replay_state = shell.replay_selected_history()

    assert replay_state.route is FrontendRoute.CHAT
    assert len(replay_state.chat.turns) == 2
    assert replay_state.chat.turns[1].status is ChatTurnStatus.REPLAYED
    assert replay_state.chat.turns[1].result is not None
    assert replay_state.chat.turns[1].result.trace_id == history_item.trace_id

    catalog_state = shell.load_catalog()

    assert catalog_state.route is FrontendRoute.CATALOG
    assert {metric.name for metric in catalog_state.catalog.metrics} >= {"revenue", "order_count"}

    eval_state = shell.run_evaluation(
        eval_suite_id="frontend_backend_flow",
        questions=("Show revenue trend.", "DROP TABLE orders"),
    )

    assert eval_state.route is FrontendRoute.EVALUATION
    assert eval_state.evaluation.latest_report is not None
    assert eval_state.evaluation.latest_report.total_cases == 2
    assert eval_state.evaluation.release_gate_status is ReleaseGateStatus.PASSED


def test_frontend_app_shell_renders_analytics_props_from_real_backend_forecast() -> None:
    backend_client: Any = TestClient(create_app())
    api_client = FrontendApiClient(_TestClientJsonTransport(backend_client))
    shell = FrontendAppShell(context=_context(), api_client=api_client)

    state = shell.submit_chat_question("Predict revenue for next month.")
    props = shell.chat_props()

    assert state.route is FrontendRoute.CHAT
    assert state.chat.turns[0].status is ChatTurnStatus.ANSWERED
    assert state.chat.turns[0].result is not None
    assert state.chat.turns[0].result.analytics is not None
    assert state.chat.turns[0].result.analytics.model_used == "moving_average"

    result_props = props.turns[0].result
    assert result_props is not None
    assert result_props.analytics is not None
    assert result_props.analytics.title == "Analytics"
    assert result_props.analytics.model_label == "Model: moving_average"
    assert result_props.analytics.anomaly_label.startswith("Anomaly level:")
    assert result_props.analytics.forecast_points_label == "Forecast points: 3"
    assert len(result_props.analytics.narrative) == 3
    assert ResultBlockType.ANALYTICS in tuple(
        block.block_type for block in result_props.blocks
    )


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_frontend_backend",
        locale=Locale.EN,
        role=UserRole.ANALYST,
        bearer_token="test-token",
    )
