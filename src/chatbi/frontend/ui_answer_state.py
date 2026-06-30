"""UI answer state for the ChatBI answer panel.

The chat store knows about conversation turns. This module knows about the
current answer area: loading, failed, partial, or completed. Keeping it small
makes the frontend state machine easy to test and easy to explain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from chatbi.core.contracts import ErrorCode
from chatbi.frontend.view_models import QueryResultViewModel, WarningBannerViewModel


class UiAnswerStatus(StrEnum):
    IDLE = "idle"
    SUBMITTING = "submitting"
    RUNNING = "running"
    PARTIAL = "partial"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class UiAnswerState:
    status: UiAnswerStatus
    trace_id: str | None
    answer_text: str | None
    table_result: dict[str, Any] | None
    chart_spec: dict[str, Any] | None
    evidence_list: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    error_code: str | None

    @property
    def has_visible_result(self) -> bool:
        return (
            self.answer_text is not None
            or self.table_result is not None
            or self.chart_spec is not None
            or bool(self.evidence_list)
        )


def idle_answer_state() -> UiAnswerState:
    return UiAnswerState(
        status=UiAnswerStatus.IDLE,
        trace_id=None,
        answer_text=None,
        table_result=None,
        chart_spec=None,
        evidence_list=[],
        warnings=[],
        error_code=None,
    )


def submitting_answer_state() -> UiAnswerState:
    return UiAnswerState(
        status=UiAnswerStatus.SUBMITTING,
        trace_id=None,
        answer_text=None,
        table_result=None,
        chart_spec=None,
        evidence_list=[],
        warnings=[],
        error_code=None,
    )


def running_answer_state(trace_id: str | None = None) -> UiAnswerState:
    return UiAnswerState(
        status=UiAnswerStatus.RUNNING,
        trace_id=trace_id,
        answer_text=None,
        table_result=None,
        chart_spec=None,
        evidence_list=[],
        warnings=[],
        error_code=None,
    )


def failed_answer_state(
    error_code: str,
    message: str,
    trace_id: str | None = None,
) -> UiAnswerState:
    return UiAnswerState(
        status=UiAnswerStatus.FAILED,
        trace_id=trace_id,
        answer_text=None,
        table_result=None,
        chart_spec=None,
        evidence_list=[],
        warnings=[{"code": error_code, "message": message}],
        error_code=error_code,
    )


def answer_state_from_result(result: QueryResultViewModel) -> UiAnswerState:
    warnings = [_warning_dict(warning) for warning in result.warnings]
    status = (
        UiAnswerStatus.PARTIAL
        if any(_is_partial_failure(warning) for warning in result.warnings)
        else UiAnswerStatus.COMPLETED
    )

    return UiAnswerState(
        status=status,
        trace_id=result.trace_id,
        answer_text=result.answer.text,
        table_result=_table_dict(result),
        chart_spec=_chart_dict(result),
        evidence_list=[
            {
                "source_id": evidence.source_id,
                "title": evidence.title,
                "citation_anchor": evidence.citation_anchor,
                "snippet": evidence.snippet,
            }
            for evidence in result.evidence
        ],
        warnings=warnings,
        error_code=None,
    )


def _is_partial_failure(warning: WarningBannerViewModel) -> bool:
    return warning.is_partial_failure or warning.code == ErrorCode.AGENT_PARTIAL_FAILURE


def _warning_dict(warning: WarningBannerViewModel) -> dict[str, Any]:
    return {
        "code": str(warning.code),
        "message": warning.message,
        "is_partial_failure": warning.is_partial_failure,
    }


def _table_dict(result: QueryResultViewModel) -> dict[str, Any] | None:
    if result.table is None:
        return None
    return {
        "columns": list(result.table.columns),
        "rows": [dict(row) for row in result.table.rows],
    }


def _chart_dict(result: QueryResultViewModel) -> dict[str, Any] | None:
    if result.chart is None:
        return None
    return {
        "chart_type": result.chart.chart_type.value,
        "x_field": result.chart.x_field,
        "y_fields": list(result.chart.y_fields),
        "title": result.chart.title,
    }


def answer_state_as_dict(state: UiAnswerState) -> Mapping[str, Any]:
    """Serialize the exact field names from spec/07."""

    return {
        "status": state.status.value,
        "trace_id": state.trace_id,
        "answer_text": state.answer_text,
        "table_result": state.table_result,
        "chart_spec": state.chart_spec,
        "evidence_list": state.evidence_list,
        "warnings": state.warnings,
        "error_code": state.error_code,
    }
