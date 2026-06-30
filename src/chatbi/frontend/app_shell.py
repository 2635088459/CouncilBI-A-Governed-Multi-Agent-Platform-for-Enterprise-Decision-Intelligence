"""Frontend application shell for the ChatBI experience.

The shell is the top-level coordinator. It does not render HTML and it does
not talk to agents. It simply wires page stores together so the frontend flow
works as one app instead of isolated pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from chatbi.frontend.analytics_state import (
    AnalyticsApiPort,
    AnalyticsPageState,
    AnalyticsPageStore,
)
from chatbi.frontend.api_client import FrontendAnalyticsRequest, FrontendUserContext
from chatbi.frontend.catalog_state import CatalogApiPort, CatalogPageState, CatalogPageStore
from chatbi.frontend.chat_state import ChatApiPort, ChatPageState, ChatSessionStore
from chatbi.frontend.component_props import (
    CatalogPageProps,
    ChatPageProps,
    AnalyticsPageProps,
    EvaluationPageProps,
    HistoryPageProps,
    TaskStatusPageProps,
    build_catalog_page_props,
    build_chat_page_props,
    build_analytics_page_props,
    build_evaluation_page_props,
    build_history_page_props,
    build_task_status_page_props,
)
from chatbi.frontend.evaluation_state import (
    EvaluationApiPort,
    EvaluationPageState,
    EvaluationPageStore,
)
from chatbi.frontend.history_state import HistoryApiPort, HistoryPageState, HistoryPageStore
from chatbi.frontend.task_status_page_state import (
    TaskStatusApiPort,
    TaskStatusPageState,
    TaskStatusPageStore,
)

if TYPE_CHECKING:
    from chatbi.frontend.app_screen_model import AppScreenModel
    from chatbi.frontend.app_shell_props import AppShellProps


class FrontendRoute(StrEnum):
    CHAT = "chat"
    HISTORY = "history"
    CATALOG = "catalog"
    ANALYTICS = "analytics"
    TASK_STATUS = "task_status"
    EVALUATION = "evaluation"


class FrontendAppApiPort(
    ChatApiPort,
    HistoryApiPort,
    CatalogApiPort,
    AnalyticsApiPort,
    TaskStatusApiPort,
    EvaluationApiPort,
    Protocol,
):
    """One API boundary that can power every frontend page store."""


@dataclass(frozen=True, slots=True)
class AppShellState:
    route: FrontendRoute
    chat: ChatPageState
    history: HistoryPageState
    catalog: CatalogPageState
    analytics: AnalyticsPageState
    task_status: TaskStatusPageState
    evaluation: EvaluationPageState


class FrontendAppShell:
    """Coordinate page stores for the v1 frontend architecture."""

    def __init__(
        self,
        context: FrontendUserContext,
        api_client: FrontendAppApiPort,
    ) -> None:
        self._context = context
        self._route = FrontendRoute.CHAT
        self._chat_store = ChatSessionStore(context=context, api_client=api_client)
        self._history_store = HistoryPageStore(context=context, api_client=api_client)
        self._catalog_store = CatalogPageStore(context=context, api_client=api_client)
        self._analytics_store = AnalyticsPageStore(context=context, api_client=api_client)
        self._task_status_store = TaskStatusPageStore(context=context, api_client=api_client)
        self._evaluation_store = EvaluationPageStore(context=context, api_client=api_client)

    @property
    def state(self) -> AppShellState:
        return AppShellState(
            route=self._route,
            chat=self._chat_store.state,
            history=self._history_store.state,
            catalog=self._catalog_store.state,
            analytics=self._analytics_store.state,
            task_status=self._task_status_store.state,
            evaluation=self._evaluation_store.state,
        )

    def chat_props(self) -> ChatPageProps:
        return build_chat_page_props(
            self._chat_store.state,
            self._context.locale,
        )

    def task_status_props(self) -> TaskStatusPageProps:
        return build_task_status_page_props(
            self._task_status_store.state,
            self._context.locale,
        )

    def history_props(self) -> HistoryPageProps:
        return build_history_page_props(
            self._history_store.state,
            self._context.locale,
        )

    def catalog_props(self) -> CatalogPageProps:
        return build_catalog_page_props(
            self._catalog_store.state,
            self._context.locale,
        )

    def analytics_props(self) -> AnalyticsPageProps:
        return build_analytics_page_props(
            self._analytics_store.state,
            self._context.locale,
        )

    def evaluation_props(self) -> EvaluationPageProps:
        return build_evaluation_page_props(
            self._evaluation_store.state,
            self._context.locale,
        )

    def shell_props(self) -> AppShellProps:
        from chatbi.frontend.app_shell_props import build_app_shell_props

        return build_app_shell_props(self.state, self._context.locale)

    def screen_model(self) -> AppScreenModel:
        from chatbi.frontend.app_screen_model import build_app_screen_model

        return build_app_screen_model(self.state, self._context.locale)

    def navigate(self, route: FrontendRoute) -> AppShellState:
        self._route = route
        return self.state

    def submit_chat_question(
        self,
        question: str,
        idempotency_key: str | None = None,
    ) -> AppShellState:
        self._chat_store.submit_question(
            question=question,
            idempotency_key=idempotency_key,
        )
        self._route = FrontendRoute.CHAT
        return self.state

    def load_history(self) -> AppShellState:
        self._history_store.load_first_page()
        self._route = FrontendRoute.HISTORY
        return self.state

    def load_next_history_page(self) -> AppShellState:
        self._history_store.load_next_page()
        self._route = FrontendRoute.HISTORY
        return self.state

    def select_history_for_replay(self, trace_id: str) -> AppShellState:
        self._history_store.select_for_replay(trace_id)
        self._route = FrontendRoute.HISTORY
        return self.state

    def replay_selected_history(self) -> AppShellState:
        selection = self._history_store.state.selected_replay
        if selection is None:
            return self.state

        self._chat_store.replay_history_item(
            trace_id=selection.trace_id,
            question=selection.question,
        )
        self._history_store.clear_selection()
        self._route = FrontendRoute.CHAT
        return self.state

    def load_catalog(self) -> AppShellState:
        self._catalog_store.load_catalog()
        self._route = FrontendRoute.CATALOG
        return self.state

    def search_catalog(self, search_query: str) -> AppShellState:
        self._catalog_store.set_search_query(search_query)
        self._route = FrontendRoute.CATALOG
        return self.state

    def select_catalog_metric(self, metric_name: str) -> AppShellState:
        self._catalog_store.select_metric(metric_name)
        self._route = FrontendRoute.CATALOG
        return self.state

    def set_analytics_request(self, request: FrontendAnalyticsRequest) -> AppShellState:
        self._analytics_store.set_request(request)
        self._route = FrontendRoute.ANALYTICS
        return self.state

    def run_analytics(self, request: FrontendAnalyticsRequest | None = None) -> AppShellState:
        if request is None:
            self._analytics_store.run_current_request()
        else:
            self._analytics_store.run_request(request)
        self._route = FrontendRoute.ANALYTICS
        return self.state

    def enqueue_analytics(self, request: FrontendAnalyticsRequest | None = None) -> AppShellState:
        if request is None:
            self._analytics_store.enqueue_current_request()
        else:
            self._analytics_store.enqueue_request(request)
        self._route = FrontendRoute.ANALYTICS
        return self.state

    def load_analytics_result(self, trace_id: str) -> AppShellState:
        self._analytics_store.load_result(trace_id)
        self._route = FrontendRoute.ANALYTICS
        return self.state

    def load_task_status(self, task_id: str) -> AppShellState:
        self._task_status_store.load_task(task_id)
        self._route = FrontendRoute.TASK_STATUS
        return self.state

    def refresh_current_task_status(self) -> AppShellState:
        self._task_status_store.load_current_task()
        self._route = FrontendRoute.TASK_STATUS
        return self.state

    def run_evaluation(
        self,
        eval_suite_id: str | None = None,
        questions: tuple[str, ...] | None = None,
    ) -> AppShellState:
        if eval_suite_id is not None:
            self._evaluation_store.set_eval_suite_id(eval_suite_id)
        if questions is not None:
            self._evaluation_store.set_questions(questions)

        self._evaluation_store.run_current_suite()
        self._route = FrontendRoute.EVALUATION
        return self.state
