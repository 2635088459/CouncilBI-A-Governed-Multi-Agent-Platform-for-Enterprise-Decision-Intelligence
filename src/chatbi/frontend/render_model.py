"""Framework-neutral render model for ChatBI frontend screens.

Component props describe what each widget needs. This module flattens those
props into a simple list of visible regions so tests can verify the screen
contract before a real browser framework is attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from chatbi.frontend.app_screen_model import AppScreenModel
from chatbi.frontend.component_props import (
    AnalyticsPageProps,
    CatalogPageProps,
    ChatPageProps,
    EvaluationPageProps,
    HistoryPageProps,
    TaskStatusPageProps,
    ComponentId,
)
from chatbi.frontend.ui_answer_state import UiAnswerStatus


class RenderRegion(StrEnum):
    APP_SHELL = "app_shell"
    NAVIGATION = "navigation"
    ACTIVE_PAGE = "active_page"
    CHAT_INPUT = "chat_input"
    SEND_BUTTON = "send_button"
    ANSWER_TEXT = "answer_text"
    TABLE = "table"
    CHART = "chart"
    EVIDENCE_LIST = "evidence_list"
    WARNING_LIST = "warning_list"
    TRACE_ID = "trace_id"
    ERROR_BOUNDARY = "error_boundary"
    HISTORY_LIST = "history_list"
    CATALOG_SEARCH = "catalog_search"
    CATALOG_LIST = "catalog_list"
    CATALOG_DETAIL = "catalog_detail"
    TASK_STATUS_CARD = "task_status_card"
    EVALUATION_REPORT = "evaluation_report"
    ANALYTICS_RESULT = "analytics_result"


@dataclass(frozen=True, slots=True)
class RenderElement:
    region: RenderRegion
    component_id: ComponentId | None
    visible: bool
    text: str | None = None
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ChatScreenRenderModel:
    elements: tuple[RenderElement, ...]

    def visible_regions(self) -> tuple[RenderRegion, ...]:
        return tuple(element.region for element in self.elements if element.visible)


@dataclass(frozen=True, slots=True)
class AppRenderModel:
    elements: tuple[RenderElement, ...]

    def visible_regions(self) -> tuple[RenderRegion, ...]:
        return tuple(element.region for element in self.elements if element.visible)


def build_app_render_model(screen: AppScreenModel) -> AppRenderModel:
    """Build the visible app-level contract for shell plus active page."""

    elements = [
        RenderElement(
            region=RenderRegion.APP_SHELL,
            component_id=None,
            visible=True,
            text=screen.shell.title,
            payload={"active_route": screen.active_route.value},
        ),
        RenderElement(
            region=RenderRegion.NAVIGATION,
            component_id=None,
            visible=True,
            payload={
                "items": [
                    {
                        "route": item.route.value,
                        "label": item.label,
                        "component_id": item.component_id.value,
                        "is_active": item.is_active,
                    }
                    for item in screen.shell.nav_items
                ]
            },
        ),
        RenderElement(
            region=RenderRegion.ACTIVE_PAGE,
            component_id=None,
            visible=True,
            payload={"route": screen.active_route.value},
        ),
    ]
    if isinstance(screen.active_page, ChatPageProps):
        elements.extend(build_chat_screen_render_model(screen.active_page).elements)
    elif isinstance(screen.active_page, HistoryPageProps):
        elements.append(_history_list_element(screen.active_page))
    elif isinstance(screen.active_page, CatalogPageProps):
        elements.extend(_catalog_elements(screen.active_page))
    elif isinstance(screen.active_page, AnalyticsPageProps):
        elements.append(_analytics_result_element(screen.active_page))
    elif isinstance(screen.active_page, TaskStatusPageProps):
        elements.append(_task_status_element(screen.active_page))
    else:
        elements.append(_evaluation_report_element(screen.active_page))
    return AppRenderModel(elements=tuple(elements))


def _history_list_element(props: HistoryPageProps) -> RenderElement:
    return RenderElement(
        region=RenderRegion.HISTORY_LIST,
        component_id=ComponentId.HISTORY_LIST,
        visible=True,
        text=props.title,
        payload={
            "items": [
                {
                    "trace_id": item.trace_id,
                    "question": item.question_text,
                    "status": item.status.value,
                    "can_replay": item.can_replay,
                }
                for item in props.items
            ],
            "can_load_more": props.can_load_more,
        },
    )


def _catalog_elements(props: CatalogPageProps) -> tuple[RenderElement, ...]:
    return (
        RenderElement(
            region=RenderRegion.CATALOG_SEARCH,
            component_id=ComponentId.CATALOG_SEARCH,
            visible=True,
            text=props.search.placeholder,
            payload={"value": props.search.value},
        ),
        RenderElement(
            region=RenderRegion.CATALOG_LIST,
            component_id=ComponentId.CATALOG_LIST,
            visible=True,
            payload={"metrics": [metric.name for metric in props.metrics]},
        ),
        RenderElement(
            region=RenderRegion.CATALOG_DETAIL,
            component_id=ComponentId.CATALOG_DETAIL,
            visible=props.selected_metric is not None,
            text=None if props.selected_metric is None else props.selected_metric.name,
        ),
    )


def _task_status_element(props: TaskStatusPageProps) -> RenderElement:
    return RenderElement(
        region=RenderRegion.TASK_STATUS_CARD,
        component_id=ComponentId.TASK_STATUS_CARD,
        visible=props.status_card is not None,
        text=None if props.status_card is None else props.status_card.label,
        payload=None
        if props.status_card is None
        else {
            "task_id": props.status_card.task_id,
            "status": props.status_card.status.value,
            "tone": props.status_card.tone,
        },
    )


def _analytics_result_element(props: AnalyticsPageProps) -> RenderElement:
    if props.result is not None:
        return RenderElement(
            region=RenderRegion.ANALYTICS_RESULT,
            component_id=ComponentId.ANALYTICS_RESULT,
            visible=True,
            text=props.result.method_label,
            payload={
                "trace_id": props.result.trace_id,
                "metric_id": props.result.metric_id,
                "forecast_points_label": props.result.forecast_points_label,
                "warning_count_label": props.result.warning_count_label,
            },
        )
    if props.task is not None:
        return RenderElement(
            region=RenderRegion.ANALYTICS_RESULT,
            component_id=ComponentId.ANALYTICS_TASK,
            visible=True,
            text=props.task.label,
            payload={
                "task_id": props.task.task_id,
                "trace_id": props.task.trace_id,
                "status": props.task.status.value,
            },
        )
    return RenderElement(
        region=RenderRegion.ANALYTICS_RESULT,
        component_id=ComponentId.ANALYTICS_RESULT,
        visible=False,
        text=props.empty_state,
    )


def _evaluation_report_element(props: EvaluationPageProps) -> RenderElement:
    return RenderElement(
        region=RenderRegion.EVALUATION_REPORT,
        component_id=ComponentId.EVALUATION_REPORT,
        visible=props.report is not None,
        text=None if props.report is None else props.report.gate_label,
        payload=None
        if props.report is None
        else {
            "tone": props.report.tone,
            "score_label": props.report.score_label,
            "failed_cases": len(props.report.failed_cases),
        },
    )


def build_chat_screen_render_model(props: ChatPageProps) -> ChatScreenRenderModel:
    """Build the visible screen contract for the chat page."""

    elements = [
        RenderElement(
            region=RenderRegion.CHAT_INPUT,
            component_id=ComponentId.CHAT_INPUT,
            visible=True,
            text=props.input.placeholder,
        ),
        RenderElement(
            region=RenderRegion.SEND_BUTTON,
            component_id=ComponentId.CHAT_SEND,
            visible=True,
            text=props.input.loading_label if props.is_loading else props.input.send_label,
            payload={"can_submit": props.input.can_submit},
        ),
    ]

    if props.error_boundary is not None:
        elements.append(
            RenderElement(
                region=RenderRegion.ERROR_BOUNDARY,
                component_id=ComponentId.ERROR_BOUNDARY,
                visible=True,
                text=props.error_boundary.message,
                payload={
                    "code": props.error_boundary.code,
                    "title": props.error_boundary.title,
                    "retryable": props.error_boundary.retryable,
                },
            )
        )

    answer_state = props.answer_state
    has_answer = answer_state.status in {
        UiAnswerStatus.PARTIAL,
        UiAnswerStatus.COMPLETED,
    }
    if has_answer and answer_state.answer_text is not None:
        elements.append(
            RenderElement(
                region=RenderRegion.ANSWER_TEXT,
                component_id=ComponentId.RESULT_CARD,
                visible=True,
                text=answer_state.answer_text,
            )
        )

    if has_answer:
        elements.extend(
            [
                RenderElement(
                    region=RenderRegion.TABLE,
                    component_id=ComponentId.RESULT_CARD,
                    visible=answer_state.table_result is not None,
                    payload=answer_state.table_result,
                ),
                RenderElement(
                    region=RenderRegion.CHART,
                    component_id=ComponentId.RESULT_CARD,
                    visible=answer_state.chart_spec is not None,
                    payload=answer_state.chart_spec,
                ),
                RenderElement(
                    region=RenderRegion.EVIDENCE_LIST,
                    component_id=ComponentId.RESULT_CARD,
                    visible=True,
                    payload={"items": answer_state.evidence_list},
                ),
                RenderElement(
                    region=RenderRegion.WARNING_LIST,
                    component_id=ComponentId.RESULT_CARD,
                    visible=True,
                    payload={"items": answer_state.warnings},
                ),
            ]
        )

    if props.trace is not None:
        elements.append(
            RenderElement(
                region=RenderRegion.TRACE_ID,
                component_id=ComponentId.TRACE_ID,
                visible=True,
                text=props.trace.label,
                payload={
                    "copy_value": props.trace.copy_value,
                    "copyable": props.trace.copyable,
                },
            )
        )

    return ChatScreenRenderModel(elements=tuple(elements))
