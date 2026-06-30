"""Top-level screen model for the ChatBI frontend app.

The app shell knows every page store. Component props know each page shape.
This module combines both into one route-aware model that a real UI framework
can render without reimplementing routing rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from chatbi.core.contracts import Locale
from chatbi.frontend.app_shell import AppShellState, FrontendRoute
from chatbi.frontend.app_shell_props import AppShellProps, build_app_shell_props
from chatbi.frontend.component_props import (
    CatalogPageProps,
    ChatPageProps,
    EvaluationPageProps,
    HistoryPageProps,
    TaskStatusPageProps,
    build_catalog_page_props,
    build_chat_page_props,
    build_evaluation_page_props,
    build_history_page_props,
    build_task_status_page_props,
)


ActivePageProps: TypeAlias = (
    ChatPageProps
    | HistoryPageProps
    | CatalogPageProps
    | TaskStatusPageProps
    | EvaluationPageProps
)


@dataclass(frozen=True, slots=True)
class AppScreenModel:
    shell: AppShellProps
    active_route: FrontendRoute
    active_page: ActivePageProps


def build_app_screen_model(
    state: AppShellState,
    locale: Locale,
) -> AppScreenModel:
    return AppScreenModel(
        shell=build_app_shell_props(state, locale),
        active_route=state.route,
        active_page=_active_page_props(state, locale),
    )


def _active_page_props(state: AppShellState, locale: Locale) -> ActivePageProps:
    if state.route is FrontendRoute.CHAT:
        return build_chat_page_props(state.chat, locale)
    if state.route is FrontendRoute.HISTORY:
        return build_history_page_props(state.history, locale)
    if state.route is FrontendRoute.CATALOG:
        return build_catalog_page_props(state.catalog, locale)
    if state.route is FrontendRoute.TASK_STATUS:
        return build_task_status_page_props(state.task_status, locale)
    return build_evaluation_page_props(state.evaluation, locale)
