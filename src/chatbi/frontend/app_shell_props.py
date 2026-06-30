"""Framework-neutral props for the ChatBI application shell.

Page props describe the current screen. Shell props describe the chrome around
the screen: app title, navigation items, and which route is active.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.core.contracts import Locale
from chatbi.frontend.app_shell import AppShellState, FrontendRoute
from chatbi.frontend.component_props import ComponentId
from chatbi.frontend.i18n import TranslationKey, translate


@dataclass(frozen=True, slots=True)
class AppNavItemProps:
    route: FrontendRoute
    label: str
    component_id: ComponentId
    is_active: bool


@dataclass(frozen=True, slots=True)
class AppShellProps:
    title: str
    active_route: FrontendRoute
    nav_items: tuple[AppNavItemProps, ...]
    tab_order: tuple[ComponentId, ...]


def build_app_shell_props(state: AppShellState, locale: Locale) -> AppShellProps:
    nav_items = tuple(
        _nav_item(route=route, state=state, locale=locale)
        for route in _route_order()
    )
    return AppShellProps(
        title=translate(TranslationKey.APP_TITLE, locale),
        active_route=state.route,
        nav_items=nav_items,
        tab_order=tuple(item.component_id for item in nav_items),
    )


def _route_order() -> tuple[FrontendRoute, ...]:
    return (
        FrontendRoute.CHAT,
        FrontendRoute.HISTORY,
        FrontendRoute.CATALOG,
        FrontendRoute.ANALYTICS,
        FrontendRoute.TASK_STATUS,
        FrontendRoute.EVALUATION,
    )


def _nav_item(
    route: FrontendRoute,
    state: AppShellState,
    locale: Locale,
) -> AppNavItemProps:
    return AppNavItemProps(
        route=route,
        label=_route_label(route, locale),
        component_id=_route_component_id(route),
        is_active=state.route is route,
    )


def _route_label(route: FrontendRoute, locale: Locale) -> str:
    if route is FrontendRoute.CHAT:
        return translate(TranslationKey.APP_TITLE, locale)
    if route is FrontendRoute.HISTORY:
        return translate(TranslationKey.HISTORY_TITLE, locale)
    if route is FrontendRoute.CATALOG:
        return translate(TranslationKey.CATALOG_TITLE, locale)
    if route is FrontendRoute.ANALYTICS:
        return translate(TranslationKey.ANALYTICS_TITLE, locale)
    if route is FrontendRoute.TASK_STATUS:
        return translate(TranslationKey.TASK_STATUS_TITLE, locale)
    return translate(TranslationKey.EVALUATION_TITLE, locale)


def _route_component_id(route: FrontendRoute) -> ComponentId:
    if route is FrontendRoute.CHAT:
        return ComponentId.NAV_CHAT
    if route is FrontendRoute.HISTORY:
        return ComponentId.NAV_HISTORY
    if route is FrontendRoute.CATALOG:
        return ComponentId.NAV_CATALOG
    if route is FrontendRoute.ANALYTICS:
        return ComponentId.NAV_ANALYTICS
    if route is FrontendRoute.TASK_STATUS:
        return ComponentId.NAV_TASK_STATUS
    return ComponentId.NAV_EVALUATION
