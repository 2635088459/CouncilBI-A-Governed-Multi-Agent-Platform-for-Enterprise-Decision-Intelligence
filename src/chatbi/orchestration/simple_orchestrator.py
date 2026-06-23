"""Minimal orchestrator for the Overall Architecture workflow."""

from __future__ import annotations

from typing import Mapping, TypeGuard, cast

from chatbi.agents.analytics_agent import (
    AnalyticsAgentRunner,
    AnalyticsModel,
    TimeSeriesPoint,
)
from chatbi.agents.rag_agent import RagAgentRunner
from chatbi.agents.sql_agent import SqlAgentRunner
from chatbi.agents.verifier_agent import VerifierAgentRunner
from chatbi.agents.visualization_agent import VisualizationAgentRunner
from chatbi.core.contracts import (
    AgentName,
    ChartSpec,
    ChartType,
    ErrorCode,
    EvidenceItem,
    GuardrailPort,
    QueryAnswer,
    QueryHistoryRecord,
    QueryRequest,
    RetrievalStats,
    TableResult,
    WarningMessage,
    new_trace_id,
)
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail
from chatbi.history.in_memory import InMemoryQueryHistory
from chatbi.knowledge import InMemoryKnowledgeStore
from chatbi.orchestration.executor import (
    PlanExecutor,
    PlanExecutionResult,
)
from chatbi.orchestration.routing import ExecutionPlanBuilder, QuestionClassifier


def _is_str_tuple(value: object) -> TypeGuard[tuple[str, ...]]:
    if not isinstance(value, tuple):
        return False
    values = cast(tuple[object, ...], value)
    return all(isinstance(item, str) for item in values)


def _is_evidence_tuple(value: object) -> TypeGuard[tuple[EvidenceItem, ...]]:
    if not isinstance(value, tuple):
        return False
    values = cast(tuple[object, ...], value)
    return all(isinstance(item, EvidenceItem) for item in values)


class SimpleOrchestrator:
    """Route one query through guardrail and history before responding."""

    def __init__(
        self,
        guardrail: GuardrailPort | None = None,
        history: InMemoryQueryHistory | None = None,
        classifier: QuestionClassifier | None = None,
        plan_builder: ExecutionPlanBuilder | None = None,
        plan_executor: PlanExecutor | None = None,
        knowledge_store: InMemoryKnowledgeStore | None = None,
    ) -> None:
        self._guardrail = guardrail or SimpleSqlGuardrail()
        self._history = history or InMemoryQueryHistory()
        self._classifier = classifier or QuestionClassifier()
        self._plan_builder = plan_builder or ExecutionPlanBuilder()
        self._plan_executor = plan_executor or PlanExecutor()
        self._knowledge_store = knowledge_store

    @property
    def history(self) -> InMemoryQueryHistory:
        return self._history

    def answer(self, request: QueryRequest, trace_id: str | None = None) -> QueryAnswer:
        active_trace_id = trace_id or new_trace_id()
        sql_candidate = self._build_sql_candidate(request)
        task_type = self._classifier.classify(request.question)
        plan = self._plan_builder.build(task_type)
        execution_result = self._plan_executor.execute(
            trace_id=active_trace_id,
            plan=plan,
            runners=self._build_runners(
                request=request,
                trace_id=active_trace_id,
                sql_candidate=sql_candidate,
            ),
        )

        sql_denial = self._sql_denial_warning(execution_result)
        if sql_denial is not None:
            answer = self._build_denied_answer(
                request=request,
                trace_id=active_trace_id,
                sql_candidate=sql_candidate,
                error_code=sql_denial.code,
                message=sql_denial.message,
            )
            self._history.save(
                QueryHistoryRecord(
                    trace_id=active_trace_id,
                    request=request,
                    answer=answer,
                    failed_error_code=sql_denial.code,
                )
            )
            return answer

        answer = self._build_success_answer(
            trace_id=active_trace_id,
            safe_sql=self._safe_sql_from_execution(execution_result, sql_candidate),
            confidence=execution_result.confidence,
            warnings=execution_result.warnings,
            chart_spec=self._chart_spec_from_execution(execution_result),
            analytics_result=self._analytics_from_execution(execution_result),
            evidence_list=self._evidence_from_execution(execution_result),
            evidence_uncertainty=self._evidence_uncertainty_from_execution(execution_result),
            retrieval_stats=self._retrieval_stats_from_execution(execution_result),
        )
        self._history.save(
            QueryHistoryRecord(
                trace_id=active_trace_id,
                request=request,
                answer=answer,
            )
        )
        return answer

    def replay(self, trace_id: str) -> QueryHistoryRecord | None:
        return self._history.get(trace_id)

    def _build_runners(
        self,
        request: QueryRequest,
        trace_id: str,
        sql_candidate: str,
    ) -> dict[
        AgentName,
        SqlAgentRunner
        | VisualizationAgentRunner
        | AnalyticsAgentRunner
        | RagAgentRunner
        | VerifierAgentRunner
    ]:
        return {
            AgentName.SQL: SqlAgentRunner(
                sql_candidate=sql_candidate,
                request=request,
                trace_id=trace_id,
                guardrail=self._guardrail,
            ),
            AgentName.VISUALIZATION: VisualizationAgentRunner(
                chart_type=ChartType.LINE,
                x_field="month",
                y_fields=("revenue",),
                title="Revenue trend",
            ),
            AgentName.ANALYTICS: AnalyticsAgentRunner(
                model=AnalyticsModel.MOVING_AVERAGE,
                metric_name="revenue",
                horizon_days=3,
                time_series=self._revenue_time_series(),
                granularity="month",
                trace_id=trace_id,
            ),
            AgentName.RAG: RagAgentRunner(
                evidence_items=self._fallback_evidence_items(),
                knowledge_store=self._knowledge_store,
                question=request.question,
                metric_context=sql_candidate,
                user_role=request.role.value,
                trace_id=trace_id,
            ),
            AgentName.VERIFIER: VerifierAgentRunner(
                verified=True,
                confidence=0.9,
                reason="Mock answer passes baseline verification.",
            ),
        }

    def _fallback_evidence_items(self) -> tuple[EvidenceItem, ...]:
        if self._knowledge_store is not None:
            return ()

        return (
            EvidenceItem(
                source_id="doc_revenue_release_notes",
                title="Revenue release notes",
                citation_anchor="doc_revenue_release_notes#p1",
                snippet="Revenue changes were linked to campaign timing.",
            ),
        )

    def _sql_denial_warning(self, execution_result: PlanExecutionResult) -> WarningMessage | None:
        for warning in execution_result.warnings:
            if warning.code is ErrorCode.SQL_DENY_STATEMENT:
                return warning
        return None

    def _safe_sql_from_execution(
        self,
        execution_result: PlanExecutionResult,
        fallback_sql: str,
    ) -> str:
        sql_output = execution_result.outputs.get(AgentName.SQL)
        if sql_output is None:
            return fallback_sql
        safe_sql = sql_output.payload.get("safe_sql")
        return safe_sql if isinstance(safe_sql, str) else fallback_sql

    def _chart_spec_from_execution(self, execution_result: PlanExecutionResult) -> ChartSpec | None:
        chart_output = execution_result.outputs.get(AgentName.VISUALIZATION)
        if chart_output is None:
            return None

        chart_type = chart_output.payload.get("chart_type")
        x_field = chart_output.payload.get("x_field")
        y_fields = chart_output.payload.get("y_fields")
        title = chart_output.payload.get("title")

        if not isinstance(chart_type, str):
            return None
        if not isinstance(x_field, str):
            return None
        if not _is_str_tuple(y_fields):
            return None
        if title is not None and not isinstance(title, str):
            return None

        return ChartSpec(
            chart_type=ChartType(chart_type),
            x_field=x_field,
            y_fields=y_fields,
            title=title,
        )

    def _evidence_from_execution(self, execution_result: PlanExecutionResult) -> tuple[EvidenceItem, ...]:
        rag_output = execution_result.outputs.get(AgentName.RAG)
        if rag_output is None:
            return ()

        evidence_items = rag_output.payload.get("evidence_items")
        if not _is_evidence_tuple(evidence_items):
            return ()
        return evidence_items

    def _evidence_uncertainty_from_execution(self, execution_result: PlanExecutionResult) -> bool:
        rag_output = execution_result.outputs.get(AgentName.RAG)
        if rag_output is None:
            return False

        uncertainty = rag_output.payload.get("uncertainty")
        return uncertainty if isinstance(uncertainty, bool) else False

    def _retrieval_stats_from_execution(
        self,
        execution_result: PlanExecutionResult,
    ) -> RetrievalStats | None:
        rag_output = execution_result.outputs.get(AgentName.RAG)
        if rag_output is None:
            return None

        retrieval_stats = rag_output.payload.get("retrieval_stats")
        return retrieval_stats if isinstance(retrieval_stats, RetrievalStats) else None

    def _analytics_from_execution(
        self,
        execution_result: PlanExecutionResult,
    ) -> Mapping[str, object] | None:
        analytics_output = execution_result.outputs.get(AgentName.ANALYTICS)
        if analytics_output is None:
            return None
        return analytics_output.payload

    def _build_sql_candidate(self, request: QueryRequest) -> str:
        stripped_question = request.question.strip()
        if self._looks_like_sql(stripped_question):
            return stripped_question
        return "SELECT month, revenue FROM revenue_by_month LIMIT 100"

    def _looks_like_sql(self, question: str) -> bool:
        first_word = question.split(maxsplit=1)[0].lower() if question else ""
        return first_word in {
            "select",
            "drop",
            "delete",
            "update",
            "insert",
            "alter",
            "truncate",
        }

    def _build_success_answer(
        self,
        trace_id: str,
        safe_sql: str,
        confidence: float,
        warnings: tuple[WarningMessage, ...],
        chart_spec: ChartSpec | None,
        analytics_result: Mapping[str, object] | None,
        evidence_list: tuple[EvidenceItem, ...],
        evidence_uncertainty: bool,
        retrieval_stats: RetrievalStats | None,
    ) -> QueryAnswer:
        return QueryAnswer(
            answer_text="Revenue trend is ready.",
            sql_text=safe_sql,
            table_result=TableResult(
                columns=("month", "revenue"),
                rows=self._revenue_rows(),
            ),
            trace_id=trace_id,
            chart_spec=chart_spec,
            analytics_result=analytics_result,
            evidence_list=evidence_list,
            evidence_uncertainty=evidence_uncertainty,
            retrieval_stats=retrieval_stats,
            confidence=confidence,
            warnings=warnings,
        )

    def _build_denied_answer(
        self,
        request: QueryRequest,
        trace_id: str,
        sql_candidate: str,
        error_code: ErrorCode,
        message: str,
    ) -> QueryAnswer:
        return QueryAnswer(
            answer_text=f"Request was blocked: {message}",
            sql_text=sql_candidate,
            table_result=TableResult(
                columns=("status", "reason"),
                rows=({"status": "blocked", "reason": message},),
            ),
            trace_id=trace_id,
            confidence=0.0,
            warnings=(
                WarningMessage(
                    code=error_code,
                    message=f"Question from {request.user_id} was blocked before execution.",
                ),
            ),
        )

    def _revenue_rows(self) -> tuple[Mapping[str, object], ...]:
        return (
            {"month": "2026-01", "revenue": 1000.0},
            {"month": "2026-02", "revenue": 1120.0},
            {"month": "2026-03", "revenue": 1180.0},
            {"month": "2026-04", "revenue": 1210.0},
            {"month": "2026-05", "revenue": 1290.0},
            {"month": "2026-06", "revenue": 1350.0},
        )

    def _revenue_time_series(self) -> tuple[TimeSeriesPoint, ...]:
        points: list[TimeSeriesPoint] = []
        for row in self._revenue_rows():
            month = row["month"]
            revenue = row["revenue"]
            if isinstance(month, str) and isinstance(revenue, int | float):
                points.append(TimeSeriesPoint(timestamp=month, value=float(revenue)))
        return tuple(points)
