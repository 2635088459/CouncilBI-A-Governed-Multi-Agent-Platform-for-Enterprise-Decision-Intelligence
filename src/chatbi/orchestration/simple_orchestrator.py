"""Minimal orchestrator for the Overall Architecture workflow."""

from __future__ import annotations

from time import perf_counter
from typing import Mapping, Protocol, TypeGuard, cast

from chatbi.analytics import AnalyticsGrain, AnalyticsService
from chatbi.analytics_repository import InMemoryAnalyticsRepository
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
from chatbi.governance import InMemoryGuardrailAuditLog, ReadOnlyQueryResult
from chatbi.governance.audit import GuardrailAuditLog
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail
from chatbi.history.in_memory import InMemoryQueryHistory
from chatbi.knowledge import InMemoryKnowledgeStore
from chatbi.orchestration.answer_verification import AnswerAssemblyVerifier
from chatbi.orchestration.analytics_runner import AnalyticsServiceRunner
from chatbi.orchestration.executor import (
    PlanExecutor,
    PlanExecutionResult,
)
from chatbi.orchestration.routing import ExecutionPlanBuilder, QuestionClassifier
from chatbi.orchestration.state import OrchestrationRequestState, RequestStateStage
from chatbi.trace_events import InMemoryTraceEventStore, TraceEvent, TraceEventRecorder, TraceEventStatus


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


class ReadOnlyQueryRunner(Protocol):
    def execute(self, database_url: str | None, sql_text: str) -> ReadOnlyQueryResult:
        ...


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
        answer_verifier: AnswerAssemblyVerifier | None = None,
        readonly_query_executor: ReadOnlyQueryRunner | None = None,
        readonly_database_url: str | None = None,
        analytics_service: AnalyticsService | None = None,
        guardrail_audit_log: InMemoryGuardrailAuditLog | None = None,
        trace_event_recorder: TraceEventRecorder | None = None,
    ) -> None:
        self._guardrail_audit_log = guardrail_audit_log or InMemoryGuardrailAuditLog()
        self._guardrail = guardrail or SimpleSqlGuardrail(audit_log=self._guardrail_audit_log)
        self._history = history or InMemoryQueryHistory()
        self._classifier = classifier or QuestionClassifier()
        self._plan_builder = plan_builder or ExecutionPlanBuilder()
        self._plan_executor = plan_executor or PlanExecutor()
        self._knowledge_store = knowledge_store
        self._answer_verifier = answer_verifier or AnswerAssemblyVerifier()
        self._readonly_query_executor = readonly_query_executor
        self._readonly_database_url = readonly_database_url
        self._analytics_service = analytics_service or AnalyticsService(
            InMemoryAnalyticsRepository()
        )
        self._trace_event_recorder = trace_event_recorder or TraceEventRecorder(
            service="orchestrator"
        )

    @property
    def history(self) -> InMemoryQueryHistory:
        return self._history

    @property
    def guardrail_audit_log(self) -> GuardrailAuditLog:
        return self._guardrail_audit_log

    @property
    def trace_event_store(self) -> InMemoryTraceEventStore:
        return self._trace_event_recorder.store

    def answer(self, request: QueryRequest, trace_id: str | None = None) -> QueryAnswer:
        active_trace_id = trace_id or new_trace_id()
        started_at = perf_counter()
        started_event = self._trace_event_recorder.start(
            trace_id=active_trace_id,
            span_name="orchestration",
        )
        self._save_request_state(
            OrchestrationRequestState(
                trace_id=active_trace_id,
                stage=RequestStateStage.RUNNING,
                input_summary={
                    "session_id": request.session_id,
                    "question_length": len(request.question),
                    "role": request.role.value,
                },
            )
        )

        def run_orchestration() -> QueryAnswer:
            return self._answer_with_active_trace(request, active_trace_id)

        try:
            answer = self._plan_executor.tracer.run_step(
                trace_id=active_trace_id,
                agent_name=AgentName.ORCHESTRATOR,
                action=run_orchestration,
            )
        except Exception as exc:
            self._save_request_state(
                OrchestrationRequestState(
                    trace_id=active_trace_id,
                    stage=RequestStateStage.FAILED,
                    input_summary={
                        "session_id": request.session_id,
                        "question_length": len(request.question),
                        "role": request.role.value,
                    },
                    error={
                        "code": ErrorCode.INTERNAL_ERROR.value,
                        "message": str(exc),
                        "retryable": True,
                    },
                    latency_ms=self._duration_ms(started_at),
                )
            )
            self._complete_orchestrator_trace_event(
                started_event=started_event,
                status=TraceEventStatus.FAILED,
            )
            raise

        self._save_request_state(
            self._request_state_from_answer(
                request=request,
                answer=answer,
                latency_ms=self._duration_ms(started_at),
            )
        )
        self._complete_orchestrator_trace_event(
            started_event=started_event,
            status=self._trace_event_status_for_answer(answer),
        )
        return answer

    def _answer_with_active_trace(self, request: QueryRequest, active_trace_id: str) -> QueryAnswer:
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

        safe_sql = self._safe_sql_from_execution(execution_result, sql_candidate)
        table_result, readonly_warning = self._table_result_for_safe_sql(safe_sql)
        warnings = self._warnings_from_execution(execution_result)
        if readonly_warning is not None:
            warnings = (*warnings, readonly_warning)

        answer = self._answer_verifier.verify(
            self._build_success_answer(
                trace_id=active_trace_id,
                safe_sql=safe_sql,
                table_result=table_result,
                confidence=execution_result.confidence,
                warnings=warnings,
                chart_spec=self._chart_spec_from_execution(execution_result),
                analytics_result=self._analytics_from_execution(execution_result),
                evidence_list=self._evidence_from_execution(execution_result),
                evidence_uncertainty=self._evidence_uncertainty_from_execution(execution_result),
                retrieval_stats=self._retrieval_stats_from_execution(execution_result),
            )
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

    def _save_request_state(self, state: OrchestrationRequestState) -> None:
        self._plan_executor.state_store.save_request_state(state)

    def _duration_ms(self, started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))

    def _complete_orchestrator_trace_event(
        self,
        started_event: TraceEvent,
        status: TraceEventStatus,
    ) -> None:
        self._trace_event_recorder.complete(started_event, status=status)

    def _trace_event_status_for_answer(self, answer: QueryAnswer) -> TraceEventStatus:
        if self._sql_denial_from_answer(answer) is not None:
            return TraceEventStatus.DEGRADED
        if answer.warnings:
            return TraceEventStatus.DEGRADED
        return TraceEventStatus.SUCCEEDED

    def _request_state_from_answer(
        self,
        request: QueryRequest,
        answer: QueryAnswer,
        latency_ms: int,
    ) -> OrchestrationRequestState:
        input_summary = {
            "session_id": request.session_id,
            "question_length": len(request.question),
            "role": request.role.value,
        }
        output_summary = {
            "confidence": answer.confidence,
            "warning_count": len(answer.warnings),
            "has_chart": answer.chart_spec is not None,
            "has_analytics": answer.analytics_result is not None,
            "evidence_count": len(answer.evidence_list),
        }

        sql_denial = self._sql_denial_from_answer(answer)
        if sql_denial is not None:
            return OrchestrationRequestState(
                trace_id=answer.trace_id,
                stage=RequestStateStage.FAILED,
                input_summary=input_summary,
                output_summary=output_summary,
                error={
                    "code": sql_denial.code.value,
                    "message": sql_denial.message,
                    "retryable": False,
                },
                latency_ms=latency_ms,
            )

        return OrchestrationRequestState(
            trace_id=answer.trace_id,
            stage=(
                RequestStateStage.DEGRADED
                if answer.warnings
                else RequestStateStage.SUCCEEDED
            ),
            input_summary=input_summary,
            output_summary=output_summary,
            latency_ms=latency_ms,
        )

    def _sql_denial_from_answer(self, answer: QueryAnswer) -> WarningMessage | None:
        denial_codes = {
            ErrorCode.SQL_DENY_STATEMENT,
            ErrorCode.SQL_DENY_OBJECT,
            ErrorCode.SQL_DENY_FUNCTION,
            ErrorCode.SQL_DENY_TIMEOUT,
        }
        for warning in answer.warnings:
            if warning.code in denial_codes:
                return warning
        return None

    def _build_runners(
        self,
        request: QueryRequest,
        trace_id: str,
        sql_candidate: str,
    ) -> dict[
        AgentName,
        SqlAgentRunner
        | VisualizationAgentRunner
        | AnalyticsServiceRunner
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
            AgentName.ANALYTICS: AnalyticsServiceRunner(
                analytics_service=self._analytics_service,
                trace_id=trace_id,
                metric_id="revenue",
                semantic_version_id="sem_v2",
                time_column="month",
                value_column="revenue",
                grain=AnalyticsGrain.MONTH,
                rows=self._revenue_rows(),
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
                sql_text=sql_candidate,
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

    def _warnings_from_execution(
        self,
        execution_result: PlanExecutionResult,
    ) -> tuple[WarningMessage, ...]:
        warnings = list(execution_result.warnings)
        verifier_warning = self._verifier_warning_from_execution(execution_result)
        if verifier_warning is not None:
            warnings.append(verifier_warning)
        return tuple(warnings)

    def _verifier_warning_from_execution(
        self,
        execution_result: PlanExecutionResult,
    ) -> WarningMessage | None:
        verifier_output = execution_result.outputs.get(AgentName.VERIFIER)
        if verifier_output is None:
            return None

        verified = verifier_output.payload.get("verified")
        if verified is not False:
            return None

        findings = verifier_output.payload.get("findings")
        if _is_str_tuple(findings):
            finding_text = "; ".join(findings)
        else:
            finding_text = "Verifier rejected the assembled answer."

        return WarningMessage(
            code=ErrorCode.VERIFICATION_FAILED,
            message=f"Verifier rejected the assembled answer: {finding_text}",
        )

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

    def _table_result_for_safe_sql(self, safe_sql: str) -> tuple[TableResult, WarningMessage | None]:
        fallback_table_result = self._fallback_table_result()
        if self._readonly_query_executor is None:
            return fallback_table_result, None

        result = self._readonly_query_executor.execute(self._readonly_database_url, safe_sql)
        if result.succeeded and result.table_result is not None:
            return result.table_result, None

        return fallback_table_result, WarningMessage(
            code=ErrorCode.INTERNAL_ERROR,
            message=result.message or "Read-only query execution failed.",
        )

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
        table_result: TableResult,
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
            table_result=table_result,
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

    def _fallback_table_result(self) -> TableResult:
        return TableResult(
            columns=("month", "revenue"),
            rows=self._revenue_rows(),
        )
