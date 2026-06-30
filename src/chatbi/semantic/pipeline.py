"""Semantic NL2SQL pipeline with guardrail handoff."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from chatbi.core.contracts import ErrorCode, GuardrailDecision, GuardrailPort, GuardrailResult, QueryRequest
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail
from chatbi.semantic.catalog import SemanticCatalog, build_default_catalog
from chatbi.semantic.question_parser import ParsedQuestion, QuestionParser
from chatbi.semantic.sql_generator import (
    GeneratedSql,
    SqlPreviewResponse,
    SqlTemplateGenerator,
    build_sql_preview_response,
)


class SemanticResolveStatus(StrEnum):
    RESOLVED = "resolved"
    NEEDS_CLARIFICATION = "needs_clarification"
    PERMISSION_DENIED = "permission_denied"


SemanticResolveRole = Literal["business_user", "analyst", "admin"]
SemanticResolveLocale = Literal["en", "zh-CN"]


@dataclass(frozen=True, slots=True)
class SemanticResolveRequest:
    trace_id: str
    user_id: str
    role: SemanticResolveRole
    question: str
    locale: SemanticResolveLocale

    def __post_init__(self) -> None:
        if not self.trace_id.strip():
            raise ValueError("trace_id is required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if self.role not in ("business_user", "analyst", "admin"):
            raise ValueError("role must be business_user, analyst, or admin")
        question_length = len(self.question)
        if question_length < 1 or question_length > 2000:
            raise ValueError("question length must be between 1 and 2000 characters")
        if self.locale not in ("en", "zh-CN"):
            raise ValueError("locale must be en or zh-CN")


@dataclass(frozen=True, slots=True)
class MetricRef:
    metric_id: str
    name: str


@dataclass(frozen=True, slots=True)
class DimensionRef:
    dimension_id: str
    name: str
    grain: str


@dataclass(frozen=True, slots=True)
class FilterRef:
    field_name: str
    operator: str
    value: Any


def _empty_metric_refs() -> list[MetricRef]:
    return []


def _empty_dimension_refs() -> list[DimensionRef]:
    return []


def _empty_filter_refs() -> list[FilterRef]:
    return []


@dataclass(frozen=True, slots=True)
class SemanticResolveResponse:
    semantic_version_id: str
    metrics: list[MetricRef] = field(default_factory=_empty_metric_refs)
    dimensions: list[DimensionRef] = field(default_factory=_empty_dimension_refs)
    time_range: object | None = None
    filters: list[FilterRef] = field(default_factory=_empty_filter_refs)
    status: SemanticResolveStatus = SemanticResolveStatus.RESOLVED
    clarification_question: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticPipelineResult:
    parsed_question: ParsedQuestion
    semantic_resolution: SemanticResolveResponse
    generated_sql: GeneratedSql | None
    sql_preview: SqlPreviewResponse | None
    guardrail_result: GuardrailResult | None
    clarification: str | None = None


class SemanticNl2SqlPipeline:
    """Parse a question, generate SQL, and hand it to the guardrail."""

    def __init__(
        self,
        catalog: SemanticCatalog | None = None,
        guardrail: GuardrailPort | None = None,
        today: date | None = None,
    ) -> None:
        self._catalog = catalog or build_default_catalog()
        self._guardrail = guardrail or SimpleSqlGuardrail()
        self._today = today
        self._sql_generator = SqlTemplateGenerator()

    def run(self, request: QueryRequest, trace_id: str) -> SemanticPipelineResult:
        parsed_question = QuestionParser(
            catalog=self._catalog,
            today=self._today,
        ).parse(request.question)
        if parsed_question.needs_clarification:
            clarification = self._clarification_message(parsed_question)
            return SemanticPipelineResult(
                parsed_question=parsed_question,
                semantic_resolution=self._semantic_resolution(
                    parsed_question=parsed_question,
                    status=SemanticResolveStatus.NEEDS_CLARIFICATION,
                    clarification_question=clarification,
                ),
                generated_sql=None,
                sql_preview=None,
                guardrail_result=None,
                clarification=clarification,
            )
        if (
            parsed_question.requested_field is not None
            and parsed_question.requested_field.is_high_sensitivity
        ):
            return SemanticPipelineResult(
                parsed_question=parsed_question,
                semantic_resolution=self._semantic_resolution(
                    parsed_question=parsed_question,
                    status=SemanticResolveStatus.PERMISSION_DENIED,
                    clarification_question=None,
                ),
                generated_sql=None,
                sql_preview=None,
                guardrail_result=self._high_sensitivity_denial(
                    field_name=parsed_question.requested_field.name,
                    trace_id=trace_id,
                ),
            )
        generated_sql = self._sql_generator.generate(parsed_question)
        sql_preview = build_sql_preview_response(generated_sql)
        guardrail_result = self._guardrail.check(
            sql_text=generated_sql.sql_text,
            request=request,
            trace_id=trace_id,
        )
        return SemanticPipelineResult(
            parsed_question=parsed_question,
            semantic_resolution=self._semantic_resolution(
                parsed_question=parsed_question,
                status=SemanticResolveStatus.RESOLVED,
                clarification_question=None,
            ),
            generated_sql=generated_sql,
            sql_preview=sql_preview,
            guardrail_result=guardrail_result,
        )

    def _semantic_resolution(
        self,
        parsed_question: ParsedQuestion,
        status: SemanticResolveStatus,
        clarification_question: str | None,
    ) -> SemanticResolveResponse:
        return SemanticResolveResponse(
            semantic_version_id=self._semantic_version_id(parsed_question),
            metrics=self._metric_refs(parsed_question),
            dimensions=self._dimension_refs(parsed_question, status),
            time_range=parsed_question.time_range if status is SemanticResolveStatus.RESOLVED else None,
            filters=[],
            status=status,
            clarification_question=clarification_question,
        )

    def _semantic_version_id(self, parsed_question: ParsedQuestion) -> str:
        if parsed_question.metric is not None:
            return parsed_question.metric.semantic_version
        if parsed_question.metric_candidates:
            return parsed_question.metric_candidates[0].semantic_version
        if parsed_question.requested_field is not None:
            return parsed_question.requested_field.semantic_version
        return "unknown"

    def _metric_refs(self, parsed_question: ParsedQuestion) -> list[MetricRef]:
        if parsed_question.metric is not None:
            return [
                MetricRef(
                    metric_id=parsed_question.metric.name,
                    name=parsed_question.metric.name,
                )
            ]
        return [
            MetricRef(metric_id=metric.name, name=metric.name)
            for metric in parsed_question.metric_candidates
        ]

    def _dimension_refs(
        self,
        parsed_question: ParsedQuestion,
        status: SemanticResolveStatus,
    ) -> list[DimensionRef]:
        if status is not SemanticResolveStatus.RESOLVED:
            return []
        if parsed_question.time_grain.value == "month":
            return [
                DimensionRef(
                    dimension_id="order_month",
                    name="order_month",
                    grain="month",
                )
            ]
        return [
            DimensionRef(
                dimension_id="order_date",
                name="order_date",
                grain="day",
            )
        ]

    def _clarification_message(self, parsed_question: ParsedQuestion) -> str:
        candidate_names = ", ".join(
            metric.name for metric in parsed_question.metric_candidates
        )
        return f"Please clarify which metric you mean: {candidate_names}."

    def _high_sensitivity_denial(self, field_name: str, trace_id: str) -> GuardrailResult:
        return GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=trace_id,
            error_code=ErrorCode.SQL_DENY_OBJECT,
            message=(
                f"Field {field_name} is high-sensitivity and cannot be queried directly. "
                "Ask for an approved aggregate metric instead."
            ),
        )
