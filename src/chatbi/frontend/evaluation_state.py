"""Evaluation page state for running quality suites from the frontend.

This page is less about daily BI usage and more about release confidence:
run a suite, inspect scores, and see whether the release gate passed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from chatbi.frontend.api_client import EvaluationRunViewModel, FrontendUserContext


class ReleaseGateStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EvaluationPageState:
    context: FrontendUserContext
    eval_suite_id: str = "backend_api_smoke"
    questions: tuple[str, ...] = ()
    latest_report: EvaluationRunViewModel | None = None
    is_running: bool = False
    error_message: str | None = None

    @property
    def release_gate_status(self) -> ReleaseGateStatus:
        if self.latest_report is None:
            return ReleaseGateStatus.NOT_RUN
        if self.latest_report.release_gate_passed:
            return ReleaseGateStatus.PASSED
        return ReleaseGateStatus.FAILED


class EvaluationApiPort(Protocol):
    def run_evaluation(
        self,
        context: FrontendUserContext,
        eval_suite_id: str,
        questions: tuple[str, ...] = (),
    ) -> EvaluationRunViewModel:
        """Run a backend evaluation suite."""
        ...


class EvaluationPageStore:
    """Small in-memory store for the Evaluation page."""

    def __init__(
        self,
        context: FrontendUserContext,
        api_client: EvaluationApiPort,
        eval_suite_id: str = "backend_api_smoke",
    ) -> None:
        self._api_client = api_client
        self._state = EvaluationPageState(
            context=context,
            eval_suite_id=eval_suite_id,
        )

    @property
    def state(self) -> EvaluationPageState:
        return self._state

    def set_eval_suite_id(self, eval_suite_id: str) -> EvaluationPageState:
        normalized_suite_id = eval_suite_id.strip()
        if not normalized_suite_id:
            raise ValueError("Evaluation suite id is required.")
        self._state = replace(
            self._state,
            eval_suite_id=normalized_suite_id,
            error_message=None,
        )
        return self._state

    def set_questions(self, questions: tuple[str, ...]) -> EvaluationPageState:
        normalized_questions = tuple(
            question.strip()
            for question in questions
            if question.strip()
        )
        self._state = replace(
            self._state,
            questions=normalized_questions,
            error_message=None,
        )
        return self._state

    def run_current_suite(self) -> EvaluationPageState:
        self._state = replace(
            self._state,
            is_running=True,
            error_message=None,
        )

        try:
            report = self._api_client.run_evaluation(
                context=self._state.context,
                eval_suite_id=self._state.eval_suite_id,
                questions=self._state.questions,
            )
        except ValueError as exc:
            self._state = replace(
                self._state,
                is_running=False,
                error_message=str(exc),
            )
            return self._state

        self._state = replace(
            self._state,
            latest_report=report,
            is_running=False,
            error_message=None,
        )
        return self._state
