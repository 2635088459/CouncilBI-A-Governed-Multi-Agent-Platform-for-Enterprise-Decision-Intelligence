"""Semantic NL2SQL pipeline with guardrail handoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from chatbi.core.contracts import ErrorCode, GuardrailDecision, GuardrailPort, GuardrailResult, QueryRequest
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail
from chatbi.semantic.catalog import SemanticCatalog, build_default_catalog
from chatbi.semantic.question_parser import ParsedQuestion, QuestionParser
from chatbi.semantic.sql_generator import GeneratedSql, SqlTemplateGenerator


@dataclass(frozen=True, slots=True)
class SemanticPipelineResult:
    parsed_question: ParsedQuestion
    generated_sql: GeneratedSql | None
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
            return SemanticPipelineResult(
                parsed_question=parsed_question,
                generated_sql=None,
                guardrail_result=None,
                clarification=self._clarification_message(parsed_question),
            )
        if (
            parsed_question.requested_field is not None
            and parsed_question.requested_field.is_high_sensitivity
        ):
            return SemanticPipelineResult(
                parsed_question=parsed_question,
                generated_sql=None,
                guardrail_result=self._high_sensitivity_denial(
                    field_name=parsed_question.requested_field.name,
                    trace_id=trace_id,
                ),
            )
        generated_sql = self._sql_generator.generate(parsed_question)
        guardrail_result = self._guardrail.check(
            sql_text=generated_sql.sql_text,
            request=request,
            trace_id=trace_id,
        )
        return SemanticPipelineResult(
            parsed_question=parsed_question,
            generated_sql=generated_sql,
            guardrail_result=guardrail_result,
        )

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
