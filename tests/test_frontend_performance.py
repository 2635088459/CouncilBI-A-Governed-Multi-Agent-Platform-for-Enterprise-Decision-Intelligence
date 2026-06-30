from time import perf_counter

from chatbi.core.contracts import Locale, UserRole
from chatbi.frontend.api_client import FrontendApiClient, FrontendUserContext
from chatbi.frontend.app_shell import FrontendAppShell
from chatbi.frontend.chat_state import ChatSessionStore
from chatbi.frontend.fixture_transport import FixtureJsonTransport
from chatbi.frontend.ui_answer_state import UiAnswerStatus


def test_first_meaningful_render_with_fixtures_stays_under_two_seconds() -> None:
    start = perf_counter()

    client = FrontendApiClient(FixtureJsonTransport())
    shell = FrontendAppShell(context=_context(), api_client=client)
    shell.submit_chat_question("show monthly revenue")
    props = shell.chat_props()

    elapsed_seconds = perf_counter() - start
    assert props.answer_state.status is UiAnswerStatus.COMPLETED
    assert props.answer_state.answer_text == "Revenue trend is ready."
    assert elapsed_seconds <= 2.0


def test_click_to_loading_state_transition_stays_under_one_hundred_ms() -> None:
    client = FrontendApiClient(FixtureJsonTransport())
    store = ChatSessionStore(context=_context(), api_client=client)

    start = perf_counter()
    state = store.start_question_submission("show monthly revenue")
    elapsed_seconds = perf_counter() - start

    assert state.is_loading is True
    assert state.answer_state.status is UiAnswerStatus.SUBMITTING
    assert elapsed_seconds <= 0.1


def _context() -> FrontendUserContext:
    return FrontendUserContext(
        user_id="u_001",
        session_id="s_001",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
        bearer_token="test-token",
    )
