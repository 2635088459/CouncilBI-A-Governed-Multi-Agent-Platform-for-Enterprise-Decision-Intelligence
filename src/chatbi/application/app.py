"""Application entry points for the Backend API slice."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from functools import lru_cache
from time import monotonic

from chatbi.api.models import (
    ApiEnvelope,
    AuditRecordPayload,
    ApiErrorCode,
    ChatQueryRequestPayload,
    CursorPagePayload,
    EvalRunRequestPayload,
    EvalRunResultPayload,
    api_error_for_warning,
    agent_timeline_payload,
    datasets_catalog_payload,
    envelope,
    error_envelope,
    history_item_payload,
    metrics_catalog_payload,
    observability_trace_payload,
    quality_dashboard_payload,
    success_envelope,
    trace_event_payload,
    to_chat_query_response,
    trace_detail_payload,
    utc_now_iso,
)
from chatbi.core.contracts import (
    AgentName,
    AgentStepStatus,
    ErrorCode,
    Locale,
    QueryAnswer,
    QueryHistoryRecord,
    QueryRequest,
    UserRole,
    new_trace_id,
)
from chatbi.core.contracts import utc_now
from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog
from chatbi.evaluation import BenchmarkExpectation, EvaluationObservation, EvaluationScorer
from chatbi.evaluation_cases import load_golden_dataset_cases
from chatbi.evaluation_repository import (
    EvalCase,
    EvalRunner,
    EvalScore,
    EvaluationRepository,
    InMemoryEvaluationRepository,
)
from chatbi.evaluation_report import eval_run_report
from chatbi.governance.audit import GuardrailAuditRecord
from chatbi.knowledge import InMemoryKnowledgeStore, RetrievalQuery
from chatbi.observability import (
    AlertEvaluator,
    InMemoryObservabilityStore,
    RuntimeRequestSample,
    TraceRecorder,
    TraceSpanName,
    TraceSpanStatus,
)
from chatbi.observability_logs import (
    InMemoryObservabilityLogStore,
    LogLevel,
    ObservabilityLogger,
)
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator
from chatbi.rate_limit import InMemorySlidingWindowRateLimitStore, RateLimitCounterStore
from chatbi.retrieval_evaluation import RetrievalEvaluationResult, RetrievalEvaluator
from chatbi.runtime_metrics import RuntimeMetricsSnapshot, runtime_metrics_snapshot
from chatbi.trace_events import (
    InMemoryTraceEventStore,
    TraceEvent,
    TraceEventRecorder,
    TraceEventStatus,
)


@lru_cache(maxsize=1)
def _golden_dataset_expected_chunk_ids_by_question() -> Mapping[str, tuple[str, ...]]:
    """Loaded once per process: golden_dataset/cases.json's real-business
    questions, keyed by normalized question text, for
    ChatBIApplication._expected_chunk_ids_for_question() to look up. Cached
    since it is re-read on every handle_eval_run() call otherwise, and the
    bundled dataset file does not change at runtime.
    """

    return {
        case.question.strip().lower(): case.expected_chunk_ids
        for case in load_golden_dataset_cases()
    }


@dataclass(frozen=True, slots=True)
class ApiAuditRecord:
    trace_id: str
    user_id: str
    endpoint: str
    status_code: int
    recorded_at: str
    error_code: ApiErrorCode | None = None


@dataclass(slots=True)
class _IdempotencyCacheEntry:
    body_fingerprint: tuple[tuple[str, str], ...]
    envelope: ApiEnvelope
    expires_at: float


class ChatBIApplication:
    """Small application facade for API use cases.

    Think of this as the service desk behind HTTP. FastAPI handles web details;
    this class owns business-friendly actions such as query, history, replay,
    catalog lookup, idempotency, and audit bookkeeping.
    """

    def __init__(
        self,
        orchestrator: SimpleOrchestrator | None = None,
        data_model_catalog: DataModelCatalog | None = None,
        rate_limit_per_minute: int = 60,
        org_rate_limit_per_minute: int | None = None,
        trace_recorder: TraceRecorder | None = None,
        observability_logger: ObservabilityLogger | None = None,
        evaluation_repository: EvaluationRepository | None = None,
        user_rate_limit_store: RateLimitCounterStore | None = None,
        org_rate_limit_store: RateLimitCounterStore | None = None,
    ) -> None:
        self._orchestrator = orchestrator or SimpleOrchestrator()
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()
        self._rate_limit_per_minute = rate_limit_per_minute
        self._org_rate_limit_per_minute = (
            rate_limit_per_minute
            if org_rate_limit_per_minute is None
            else org_rate_limit_per_minute
        )
        self._user_rate_limit_store = user_rate_limit_store or InMemorySlidingWindowRateLimitStore()
        self._org_rate_limit_store = org_rate_limit_store or InMemorySlidingWindowRateLimitStore()
        self._idempotency_cache: dict[tuple[str, str], _IdempotencyCacheEntry] = {}
        self._audit_records: list[ApiAuditRecord] = []
        self._evaluation_scorer = EvaluationScorer()
        self._trace_recorder = trace_recorder or TraceRecorder()
        self._alert_evaluator = AlertEvaluator()
        self._runtime_samples: list[RuntimeRequestSample] = []
        self._latest_eval_result: EvalRunResultPayload | None = None
        self._latest_eval_result_by_org: dict[str, EvalRunResultPayload] = {}
        self._observability_logger = observability_logger or ObservabilityLogger()
        self._evaluation_repository = evaluation_repository or InMemoryEvaluationRepository()
        self._eval_runner = EvalRunner(self._evaluation_repository)
        self._trace_event_recorder = TraceEventRecorder(service="backend-api")

    @property
    def orchestrator(self) -> SimpleOrchestrator:
        return self._orchestrator

    @property
    def audit_records(self) -> tuple[ApiAuditRecord, ...]:
        return tuple(self._audit_records)

    @property
    def observability_store(self) -> InMemoryObservabilityStore:
        return self._trace_recorder.store

    @property
    def observability_log_store(self) -> InMemoryObservabilityLogStore:
        return self._observability_logger.store

    @property
    def evaluation_repository(self) -> EvaluationRepository:
        return self._evaluation_repository

    @property
    def trace_event_store(self) -> InMemoryTraceEventStore:
        return self._trace_event_recorder.store

    def runtime_metrics_snapshot(self) -> RuntimeMetricsSnapshot:
        return runtime_metrics_snapshot(tuple(self._runtime_samples))

    def record_api_audit(
        self,
        trace_id: str,
        user_id: str,
        endpoint: str,
        status_code: int,
        error_code: ApiErrorCode | None = None,
    ) -> None:
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint=endpoint,
            status_code=status_code,
            error_code=error_code,
        )

    def handle_chat_query(
        self,
        payload: ChatQueryRequestPayload,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        org_id: str = "org_legacy",
    ) -> ApiEnvelope:
        active_trace_id = trace_id or new_trace_id()
        started_at = monotonic()
        request_trace_event = self._trace_event_recorder.start(
            trace_id=active_trace_id,
            span_name=TraceSpanName.REQUEST_RECEIVED.value,
        )
        self._trace_recorder.record(
            trace_id=active_trace_id,
            span_name=TraceSpanName.REQUEST_RECEIVED,
            attributes={
                "endpoint": "/api/v1/chat/query",
                "locale": payload.locale.value,
                "role": payload.role.value,
            },
        )
        self._observability_logger.record(
            trace_id=active_trace_id,
            level=LogLevel.INFO,
            message=f"Received chat query from {payload.user_id}: {payload.question}",
            endpoint="/api/v1/chat/query",
            user_id=payload.user_id,
            attributes={
                "session_id": payload.session_id,
                "question": payload.question,
                "role": payload.role.value,
            },
        )
        rate_limited = self._rate_limit_response(
            user_id=payload.user_id,
            org_id=org_id,
            trace_id=active_trace_id,
            endpoint="/api/v1/chat/query",
        )
        if rate_limited is not None:
            self._record_response_sent_span(rate_limited, status_code=429)
            self._record_runtime_sample(
                trace_id=rate_limited.trace_id,
                endpoint="/api/v1/chat/query",
                status_code=429,
                started_at=started_at,
            )
            self._complete_request_trace_event(
                started_event=request_trace_event,
                response=rate_limited,
                status_code=429,
            )
            return rate_limited

        cached = self._get_cached_query(payload, idempotency_key)
        if cached is not None:
            self._audit(
                trace_id=cached.trace_id,
                user_id=payload.user_id,
                endpoint="/api/v1/chat/query",
                status_code=200,
            )
            self._record_response_sent_span(
                cached,
                status_code=200,
                attributes={"cache_hit": True},
            )
            self._record_runtime_sample(
                trace_id=cached.trace_id,
                endpoint="/api/v1/chat/query",
                status_code=200,
                started_at=started_at,
            )
            self._complete_request_trace_event(
                started_event=request_trace_event,
                response=cached,
                status_code=200,
            )
            return cached

        request = payload.to_domain()
        self._trace_recorder.record(
            trace_id=active_trace_id,
            span_name=TraceSpanName.ORCHESTRATION_PLANNED,
            attributes={"idempotency_key_present": idempotency_key is not None},
        )
        answer = self._orchestrator.answer(request, trace_id=active_trace_id)
        self._record_answer_spans(answer)
        response = to_chat_query_response(
            answer,
            agent_timeline=self._agent_timeline_for_answer(answer),
        )
        response_envelope = success_envelope(response)

        if answer.warnings:
            first_warning = answer.warnings[0]
            response_envelope = error_envelope(
                code=api_error_for_warning(first_warning),
                message=first_warning.message,
                trace_id=answer.trace_id,
                data=response_envelope.data,
                warnings=answer.warnings,
            )

        self._set_cached_query(payload, idempotency_key, response_envelope)
        self._audit(
            trace_id=response_envelope.trace_id,
            user_id=payload.user_id,
            endpoint="/api/v1/chat/query",
            status_code=200,
            error_code=response_envelope.code if isinstance(response_envelope.code, ApiErrorCode) else None,
        )
        self._record_response_sent_span(response_envelope, status_code=200)
        self._observability_logger.record(
            trace_id=response_envelope.trace_id,
            level=LogLevel.INFO,
            message="Sent chat query response.",
            endpoint="/api/v1/chat/query",
            user_id=payload.user_id,
            attributes={
                "api_code": str(response_envelope.code),
                "warning_count": len(response_envelope.warnings),
            },
        )
        self._record_runtime_sample(
            trace_id=response_envelope.trace_id,
            endpoint="/api/v1/chat/query",
            status_code=200,
            started_at=started_at,
        )
        self._complete_request_trace_event(
            started_event=request_trace_event,
            response=response_envelope,
            status_code=200,
        )
        return response_envelope

    def _agent_timeline_for_answer(self, answer: QueryAnswer) -> tuple[dict[str, object], ...]:
        events = self._orchestrator.agent_trace_events(answer.trace_id)
        timeline: list[dict[str, object]] = []
        for agent_name in (
            AgentName.ORCHESTRATOR,
            AgentName.SQL,
            AgentName.RAG,
            AgentName.ANALYTICS,
            AgentName.VISUALIZATION,
            AgentName.VERIFIER,
        ):
            terminal_events = [
                event
                for event in events
                if event.agent_name is agent_name and event.status is not AgentStepStatus.STARTED
            ]
            if not terminal_events:
                timeline.append(
                    {
                        "agent_name": agent_name.value,
                        "status": "not_planned",
                        "duration_ms": None,
                        "summary": "No planned step for this query type.",
                        "agent_trace_id": None,
                    }
                )
                continue
            timeline.append(dict(agent_timeline_payload(terminal_events[-1])))

        unsupported = any(
            warning.code is ErrorCode.UNSUPPORTED_QUESTION for warning in answer.warnings
        )
        timeline.append(
            {
                "agent_name": "answer_synthesis",
                "status": "not_planned" if unsupported else ("succeeded" if answer.answer_text else "failed"),
                "duration_ms": None,
                "summary": (
                    "Answer synthesis was not run because the question was outside supported business domains."
                    if unsupported
                    else "Final answer synthesized through the configured LLM gateway from safe SQL rows and evidence context."
                ),
                "agent_trace_id": f"ans_{answer.trace_id.removeprefix('trc_')}",
            }
        )
        return tuple(timeline)

    def handle_chat_history(
        self,
        user_id: str,
        trace_id: str,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint="/api/v1/chat/history",
        )
        if rate_limited is not None:
            return rate_limited

        bounded_page_size = min(max(page_size, 1), 100)
        records = sorted(
            (
                record
                for record in self._orchestrator.history.list_all()
                if record.request.user_id == user_id
            ),
            key=lambda record: record.created_at,
            reverse=True,
        )
        start_index = self._cursor_to_index(cursor)
        page_records = records[start_index : start_index + bounded_page_size]
        next_index = start_index + len(page_records)
        next_cursor = str(next_index) if next_index < len(records) else None
        page = CursorPagePayload(
            items=tuple(asdict(history_item_payload(record)) for record in page_records),
            next_cursor=next_cursor,
            page_size=bounded_page_size,
        )
        response = envelope(
            data={
                "items": page.items,
                "next_cursor": page.next_cursor,
                "page_size": page.page_size,
            },
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint="/api/v1/chat/history",
            status_code=200,
        )
        return response

    def handle_query_detail(self, trace_id: str, user_id: str) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint=f"/api/v1/query/{trace_id}",
        )
        if rate_limited is not None:
            return rate_limited

        record = self._orchestrator.replay(trace_id)
        if record is None or record.request.user_id != user_id:
            response = error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message="Trace id was not found.",
                trace_id=trace_id,
            )
            self._audit(
                trace_id=trace_id,
                user_id=user_id,
                endpoint=f"/api/v1/query/{trace_id}",
                status_code=404,
                error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            )
            return response

        detail = trace_detail_payload(record)
        response = envelope(
            data={
                "trace_id": detail.trace_id,
                "request": detail.request,
                "answer": detail.answer,
                "status": detail.status,
                "created_at": detail.created_at,
                "failed_error_code": detail.failed_error_code,
            },
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint=f"/api/v1/query/{trace_id}",
            status_code=200,
        )
        return response

    def handle_metrics_catalog(self, user_id: str, trace_id: str) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint="/api/v1/metrics/catalog",
        )
        if rate_limited is not None:
            return rate_limited

        response = envelope(
            data={"metrics": metrics_catalog_payload(self._data_model_catalog)},
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint="/api/v1/metrics/catalog",
            status_code=200,
        )
        return response

    def handle_datasets_catalog(self, user_id: str, trace_id: str) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint="/api/v1/datasets/catalog",
        )
        if rate_limited is not None:
            return rate_limited

        response = envelope(
            data={"datasets": datasets_catalog_payload(self._data_model_catalog)},
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint="/api/v1/datasets/catalog",
            status_code=200,
        )
        return response

    def handle_audit_detail(self, trace_id: str, user_id: str) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint=f"/api/v1/audit/{trace_id}",
        )
        if rate_limited is not None:
            return rate_limited

        records = tuple(record for record in self._audit_records if record.trace_id == trace_id)
        if not records:
            response = error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message="No audit records were found for this trace id.",
                trace_id=trace_id,
            )
            self._audit(
                trace_id=trace_id,
                user_id=user_id,
                endpoint=f"/api/v1/audit/{trace_id}",
                status_code=404,
                error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            )
            return response

        audit_items = tuple(asdict(self._audit_payload(record)) for record in records)
        response = envelope(
            data={
                "trace_id": trace_id,
                "items": audit_items,
                "count": len(audit_items),
            },
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint=f"/api/v1/audit/{trace_id}",
            status_code=200,
        )
        return response

    def handle_observability_trace_detail(self, trace_id: str, user_id: str) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint=f"/api/v1/observability/traces/{trace_id}",
        )
        if rate_limited is not None:
            return rate_limited

        replay = self._trace_recorder.store.replay(trace_id)
        if replay is None:
            response = error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message="No observability trace was found for this trace id.",
                trace_id=trace_id,
            )
            self._audit(
                trace_id=trace_id,
                user_id=user_id,
                endpoint=f"/api/v1/observability/traces/{trace_id}",
                status_code=404,
                error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            )
            return response

        payload = observability_trace_payload(replay)
        query_record = self._orchestrator.replay(trace_id)
        response = envelope(
            data={
                "trace_id": payload.trace_id,
                "completed": payload.completed,
                "spans": payload.spans,
                "trace_events": tuple(
                    asdict(trace_event_payload(event))
                    for event in self._trace_events_for_trace_id(trace_id)
                ),
                "query_detail": (
                    None
                    if query_record is None
                    else self._query_detail_data(query_record)
                ),
                "api_audit": self._api_audit_items(trace_id),
                "guardrail_audit": self._guardrail_audit_data(trace_id),
                "logs": self._observability_log_items(trace_id),
            },
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint=f"/api/v1/observability/traces/{trace_id}",
            status_code=200,
        )
        return response

    def handle_quality_dashboard(
        self,
        user_id: str,
        trace_id: str,
        org_id: str = "org_legacy",
    ) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint="/api/v1/quality/dashboard",
        )
        if rate_limited is not None:
            return rate_limited

        samples = tuple(self._runtime_samples)
        now = utc_now()
        dashboard = quality_dashboard_payload(
            slo_statuses=self._alert_evaluator.slo_statuses(samples=samples, now=now),
            alerts=self._alert_evaluator.evaluate(samples=samples, now=now),
            latest_eval_result=self._latest_eval_result_by_org.get(
                org_id,
                self._latest_eval_result if org_id == "org_legacy" else None,
            ),
        )
        response = envelope(
            data={
                "slo_statuses": dashboard.slo_statuses,
                "alerts": dashboard.alerts,
                "release_gate": dashboard.release_gate,
                "active_slo_count": dashboard.active_slo_count,
            },
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint="/api/v1/quality/dashboard",
            status_code=200,
        )
        return response

    def handle_eval_run(
        self,
        user_id: str,
        trace_id: str,
        payload: EvalRunRequestPayload,
        org_id: str = "org_legacy",
    ) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint="/api/v1/evals/run",
        )
        if rate_limited is not None:
            return rate_limited

        questions = payload.questions or self._default_eval_questions()
        observations = tuple(
            self._run_eval_case_observation(
                user_id=user_id,
                eval_suite_id=payload.eval_suite_id,
                question=question,
                locale=payload.locale,
                role=payload.role,
            )
            for question in questions
        )
        expectations = self._benchmark_expectations(questions)
        cases = self._build_eval_cases(observations, expectations)
        retrieval_results = self._evaluate_retrieval(cases)
        retrieval_metrics = (
            RetrievalEvaluator().aggregate(retrieval_results) if retrieval_results else None
        )
        result = self._evaluation_scorer.score_suite(
            eval_suite_id=payload.eval_suite_id,
            observations=observations,
            expectations=expectations,
            retrieval_metrics=retrieval_metrics,
        )
        self._persist_eval_run_result(
            eval_run_id=result.eval_run_id,
            eval_suite_id=payload.eval_suite_id,
            cases=cases,
            observations=observations,
            expectations=expectations,
            retrieval_results=retrieval_results,
            org_id=org_id,
        )
        if org_id == "org_legacy":
            self._latest_eval_result = result
        self._latest_eval_result_by_org[org_id] = result
        response = envelope(
            data=asdict(result),
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint="/api/v1/evals/run",
            status_code=200,
        )
        return response

    def handle_eval_report(
        self,
        user_id: str,
        trace_id: str,
        eval_run_id: str,
        org_id: str = "org_legacy",
    ) -> ApiEnvelope:
        rate_limited = self._rate_limit_response(
            user_id=user_id,
            trace_id=trace_id,
            endpoint=f"/api/v1/evals/{eval_run_id}",
        )
        if rate_limited is not None:
            return rate_limited

        report = eval_run_report(self._evaluation_repository, eval_run_id, org_id=org_id)
        if report is None:
            response = error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message="Eval run id was not found.",
                trace_id=trace_id,
            )
            self._audit(
                trace_id=trace_id,
                user_id=user_id,
                endpoint=f"/api/v1/evals/{eval_run_id}",
                status_code=404,
                error_code=ApiErrorCode.REQ_INVALID_ARGUMENT,
            )
            return response

        response = envelope(data=report.to_payload(), trace_id=trace_id)
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint=f"/api/v1/evals/{eval_run_id}",
            status_code=200,
        )
        return response

    def handle_health_check(self, user_id: str, trace_id: str) -> ApiEnvelope:
        response = envelope(
            data={
                "status": "ok",
                "service": "chatbi-api",
            },
            trace_id=trace_id,
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint="/api/v1/health",
            status_code=200,
        )
        return response

    def _rate_limit_response(
        self,
        user_id: str,
        trace_id: str,
        endpoint: str,
        org_id: str | None = None,
    ) -> ApiEnvelope | None:
        if self._rate_limit_per_minute <= 0:
            user_rate_limited = False
        else:
            user_rate_limited = self._user_rate_limit_store.record_and_check_limited(
                key=f"user:{user_id}",
                limit_per_minute=self._rate_limit_per_minute,
                now=monotonic(),
            )
        if user_rate_limited:
            return self._rate_limited_response(
                trace_id=trace_id,
                user_id=user_id,
                endpoint=endpoint,
                scope="user",
                limit_per_minute=self._rate_limit_per_minute,
            )

        now = monotonic()
        if org_id is not None and self._org_rate_limit_per_minute > 0:
            org_rate_limited = self._org_rate_limit_store.record_and_check_limited(
                key=f"organization:{org_id}",
                limit_per_minute=self._org_rate_limit_per_minute,
                now=now,
            )
            if org_rate_limited:
                return self._rate_limited_response(
                    trace_id=trace_id,
                    user_id=user_id,
                    endpoint=endpoint,
                    scope="organization",
                    limit_per_minute=self._org_rate_limit_per_minute,
                )

        return None

    def _rate_limited_response(
        self,
        *,
        trace_id: str,
        user_id: str,
        endpoint: str,
        scope: str,
        limit_per_minute: int,
    ) -> ApiEnvelope:
        response = error_envelope(
            code=ApiErrorCode.RATE_LIMITED,
            message=f"Too many requests for this {scope}. Please retry later.",
            trace_id=trace_id,
            data={
                "retry_after_seconds": 60,
                "scope": scope,
                "limit_per_minute": limit_per_minute,
            },
        )
        self._audit(
            trace_id=trace_id,
            user_id=user_id,
            endpoint=endpoint,
            status_code=429,
            error_code=ApiErrorCode.RATE_LIMITED,
        )
        return response

    def _get_cached_query(
        self,
        payload: ChatQueryRequestPayload,
        idempotency_key: str | None,
    ) -> ApiEnvelope | None:
        if idempotency_key is None:
            return None

        cache_key = (payload.user_id, idempotency_key)
        entry = self._idempotency_cache.get(cache_key)
        if entry is None or entry.expires_at < monotonic():
            self._idempotency_cache.pop(cache_key, None)
            return None
        if entry.body_fingerprint != self._fingerprint(payload):
            return error_envelope(
                code=ApiErrorCode.REQ_INVALID_ARGUMENT,
                message="Idempotency-Key was reused with a different request body.",
                trace_id=entry.envelope.trace_id,
            )
        return entry.envelope

    def _set_cached_query(
        self,
        payload: ChatQueryRequestPayload,
        idempotency_key: str | None,
        response: ApiEnvelope,
    ) -> None:
        if idempotency_key is None:
            return
        self._idempotency_cache[(payload.user_id, idempotency_key)] = _IdempotencyCacheEntry(
            body_fingerprint=self._fingerprint(payload),
            envelope=response,
            expires_at=monotonic() + 60,
        )

    def _fingerprint(self, payload: ChatQueryRequestPayload) -> tuple[tuple[str, str], ...]:
        return (
            ("locale", str(payload.locale)),
            ("question", payload.question),
            ("role", str(payload.role)),
            ("session_id", payload.session_id),
            ("user_id", payload.user_id),
        )

    def _cursor_to_index(self, cursor: str | None) -> int:
        if cursor is None:
            return 0
        try:
            return max(0, int(cursor))
        except ValueError:
            return 0

    def _audit(
        self,
        trace_id: str,
        user_id: str,
        endpoint: str,
        status_code: int,
        error_code: ApiErrorCode | None = None,
    ) -> None:
        self._audit_records.append(
            ApiAuditRecord(
                trace_id=trace_id,
                user_id=user_id,
                endpoint=endpoint,
                status_code=status_code,
                recorded_at=utc_now_iso(),
                error_code=error_code,
            )
        )

    def _audit_payload(self, record: ApiAuditRecord) -> AuditRecordPayload:
        return AuditRecordPayload(
            trace_id=record.trace_id,
            user_id=record.user_id,
            endpoint=record.endpoint,
            status_code=record.status_code,
            recorded_at=record.recorded_at,
            error_code=record.error_code,
        )

    def _query_detail_data(self, record: QueryHistoryRecord) -> dict[str, object]:
        detail = trace_detail_payload(record)
        return {
            "trace_id": detail.trace_id,
            "request": {
                "user_id": detail.request["user_id"],
                "session_id": detail.request["session_id"],
                "question": detail.request["question"],
                "locale": record.request.locale.value,
                "role": record.request.role.value,
            },
            "answer": detail.answer,
            "status": detail.status.value,
            "created_at": detail.created_at,
            "failed_error_code": (
                None
                if detail.failed_error_code is None
                else detail.failed_error_code.value
            ),
        }

    def _trace_events_for_trace_id(self, trace_id: str) -> tuple[TraceEvent, ...]:
        events = (
            *self._trace_event_recorder.store.list_by_trace_id(trace_id),
            *self._orchestrator.trace_event_store.list_by_trace_id(trace_id),
        )
        return tuple(
            sorted(
                events,
                key=lambda event: (
                    event.started_at,
                    "" if event.ended_at is None else event.ended_at.isoformat(),
                    event.service,
                ),
            )
        )

    def _api_audit_items(self, trace_id: str) -> tuple[dict[str, object], ...]:
        return tuple(
            asdict(self._audit_payload(record))
            for record in self._audit_records
            if record.trace_id == trace_id
        )

    def _guardrail_audit_data(self, trace_id: str) -> dict[str, object] | None:
        record = self._orchestrator.guardrail_audit_log.get(trace_id)
        if record is None:
            return None
        return self._guardrail_audit_record_data(record)

    def _guardrail_audit_record_data(self, record: GuardrailAuditRecord) -> dict[str, object]:
        return {
            "audit_event_id": record.audit_event_id,
            "trace_id": record.trace_id,
            "user_id": record.user_id,
            "role": record.role.value,
            "original_sql": record.original_sql,
            "decision": record.decision.value,
            "safe_sql": record.safe_sql,
            "error_code": None if record.error_code is None else record.error_code.value,
            "message": record.message,
            "occurred_at": record.occurred_at.isoformat(),
        }

    def _observability_log_items(self, trace_id: str) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "trace_id": record.trace_id,
                "level": record.level.value,
                "message": record.message,
                "endpoint": record.endpoint,
                "user_id": record.user_id,
                "service": record.service,
                "event": record.event,
                "request_id": record.request_id,
                "attributes": record.attributes,
                "recorded_at": record.recorded_at.isoformat(),
            }
            for record in self._observability_logger.store.list_by_trace_id(trace_id)
        )

    def _record_answer_spans(self, answer: QueryAnswer) -> None:
        self._trace_recorder.record(
            trace_id=answer.trace_id,
            span_name=TraceSpanName.SQL_GENERATED,
            attributes={
                "sql_text": answer.sql_text,
            },
        )
        guardrail_blocked = any(
            api_error_for_warning(warning) is ApiErrorCode.SQL_GUARDRAIL_BLOCKED
            for warning in answer.warnings
        )
        self._trace_recorder.record(
            trace_id=answer.trace_id,
            span_name=TraceSpanName.SQL_GUARDRAIL_CHECKED,
            status=TraceSpanStatus.FAILED if guardrail_blocked else TraceSpanStatus.SUCCEEDED,
            attributes={
                "decision": "deny" if guardrail_blocked else "allow",
            },
        )

        if answer.evidence_list or answer.evidence_uncertainty:
            self._trace_recorder.record(
                trace_id=answer.trace_id,
                span_name=TraceSpanName.RAG_RETRIEVED,
                attributes={
                    "evidence_count": len(answer.evidence_list),
                    "evidence_uncertainty": answer.evidence_uncertainty,
                },
            )

        if answer.analytics_result is not None:
            self._trace_recorder.record(
                trace_id=answer.trace_id,
                span_name=TraceSpanName.ANALYTICS_DONE,
                attributes={
                    "result_keys": tuple(answer.analytics_result.keys()),
                },
            )

    def _record_response_sent_span(
        self,
        response: ApiEnvelope,
        status_code: int,
        attributes: dict[str, object] | None = None,
    ) -> None:
        active_attributes: dict[str, object] = {
            "status_code": status_code,
            "api_code": str(response.code),
        }
        if attributes is not None:
            active_attributes.update(attributes)

        self._trace_recorder.record(
            trace_id=response.trace_id,
            span_name=TraceSpanName.RESPONSE_SENT,
            status=TraceSpanStatus.FAILED if status_code >= 500 else TraceSpanStatus.SUCCEEDED,
            attributes=active_attributes,
        )

    def _record_runtime_sample(
        self,
        trace_id: str,
        endpoint: str,
        status_code: int,
        started_at: float,
    ) -> None:
        self._runtime_samples.append(
            RuntimeRequestSample(
                trace_id=trace_id,
                endpoint=endpoint,
                status_code=status_code,
                latency_ms=max(0, int((monotonic() - started_at) * 1000)),
                occurred_at=utc_now(),
            )
        )

    def _complete_request_trace_event(
        self,
        started_event: TraceEvent,
        response: ApiEnvelope,
        status_code: int,
    ) -> None:
        self._trace_event_recorder.complete(
            started_event,
            status=self._trace_event_status_for_response(response, status_code),
        )

    def _trace_event_status_for_response(
        self,
        response: ApiEnvelope,
        status_code: int,
    ) -> TraceEventStatus:
        if status_code >= 500:
            return TraceEventStatus.FAILED
        if status_code >= 400 or response.code != 0:
            return TraceEventStatus.DEGRADED
        return TraceEventStatus.SUCCEEDED

    def _run_eval_case_observation(
        self,
        user_id: str,
        eval_suite_id: str,
        question: str,
        locale: Locale,
        role: UserRole,
    ) -> EvaluationObservation:
        case_trace_id = new_trace_id()
        started_at = monotonic()
        answer = self._orchestrator.answer(
            QueryRequest(
                user_id=user_id,
                session_id=f"eval_{eval_suite_id}",
                question=question,
                locale=locale,
                role=role,
            ),
            trace_id=case_trace_id,
        )
        latency_ms = max(0, int((monotonic() - started_at) * 1000))
        error_code = api_error_for_warning(answer.warnings[0]) if answer.warnings else None
        return EvaluationObservation(
            question=question,
            trace_id=case_trace_id,
            sql_text=answer.sql_text,
            confidence=answer.confidence,
            error_code=error_code,
            evidence_count=len(answer.evidence_list),
            claim_count=1 if answer.answer_text.strip() else 0,
            unsupported_claim_count=1 if answer.evidence_uncertainty else 0,
            latency_ms=latency_ms,
        )

    def _build_eval_cases(
        self,
        observations: tuple[EvaluationObservation, ...],
        expectations: dict[str, BenchmarkExpectation],
    ) -> tuple[EvalCase, ...]:
        return tuple(
            EvalCase(
                case_id=self._eval_case_id(index),
                question=observation.question,
                expected_sql_fragments=(
                    expectations[observation.question].expected_tables
                    + expectations[observation.question].expected_fields
                ),
                expected_chunk_ids=self._expected_chunk_ids_for_question(observation.question),
                permission_context={"source": "api_eval_run"},
            )
            for index, observation in enumerate(observations, start=1)
        )

    def _expected_chunk_ids_for_question(self, question: str) -> tuple[str, ...]:
        """FR-FV03-024: opts a case into retrieval scoring only when its
        question exactly matches one of the real-business Golden Dataset's
        own canonical questions (golden_dataset/cases.json — every label
        there was verified against the real seeded content, see
        load_golden_dataset_cases()'s docstring); every other question
        (SQL-only benchmarks, arbitrary caller-supplied text) has no ground
        truth to score against and stays opted out via the empty-tuple
        default, matching expected_sql_fragments' convention.
        """

        return _golden_dataset_expected_chunk_ids_by_question().get(question.strip().lower(), ())

    def _evaluate_retrieval(
        self,
        cases: tuple[EvalCase, ...],
    ) -> tuple[RetrievalEvaluationResult, ...]:
        knowledge_store = self._orchestrator.knowledge_store
        if knowledge_store is None:
            return ()
        return RetrievalEvaluator().evaluate(cases, self._retrieve_chunk_ids_fn(knowledge_store))

    def _retrieve_chunk_ids_fn(
        self,
        knowledge_store: InMemoryKnowledgeStore,
    ) -> Callable[[str], tuple[str, ...]]:
        def retrieve_fn(question: str) -> tuple[str, ...]:
            result = knowledge_store.retrieve(
                RetrievalQuery(question=question, requesting_user_id="eval_runner", top_k=5)
            )
            return tuple(
                f"{item.citation_anchor.split('#chunk-')[0]}_chunk_{item.citation_anchor.split('#chunk-')[1]}"
                for item in result.evidence_list
            )

        return retrieve_fn

    def _persist_eval_run_result(
        self,
        eval_run_id: str,
        eval_suite_id: str,
        cases: tuple[EvalCase, ...],
        observations: tuple[EvaluationObservation, ...],
        expectations: dict[str, BenchmarkExpectation],
        retrieval_results: tuple[RetrievalEvaluationResult, ...],
        org_id: str = "org_legacy",
    ) -> None:
        observations_by_question = {
            observation.question: observation
            for observation in observations
        }
        retrieval_results_by_case_id = {result.case_id: result for result in retrieval_results}
        self._eval_runner.run(
            eval_suite_id=eval_suite_id,
            cases=cases,
            score_case=lambda case: self._eval_score_for_case(
                case=case,
                observation=observations_by_question[case.question],
                expectation=expectations[case.question],
                retrieval_result=retrieval_results_by_case_id.get(case.case_id),
            ),
            eval_run_id=eval_run_id,
            org_id=org_id,
        )

    def _eval_score_for_case(
        self,
        case: EvalCase,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
        retrieval_result: RetrievalEvaluationResult | None = None,
    ) -> EvalScore:
        case_result = self._evaluation_scorer.score_case(
            observation=observation,
            expectation=expectation,
        )
        return EvalScore(
            case_id=case.case_id,
            sql_correct=self._eval_sql_correct(observation, expectation),
            sql_safe=self._eval_sql_safe(observation, expectation),
            rag_faithful=self._eval_rag_faithful(observation, expectation),
            answer_quality_score=case_result.score,
            retrieval_hit_at_3=retrieval_result.hit_at_3 if retrieval_result is not None else None,
            retrieval_reciprocal_rank=(
                retrieval_result.reciprocal_rank_value if retrieval_result is not None else None
            ),
        )

    def _eval_sql_correct(
        self,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
    ) -> bool:
        if expectation.dangerous_sql:
            return True
        expected_tokens = expectation.expected_tables + expectation.expected_fields
        sql_text = observation.sql_text.lower()
        return all(token.lower() in sql_text for token in expected_tokens)

    def _eval_sql_safe(
        self,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
    ) -> bool:
        if expectation.dangerous_sql:
            return observation.error_code is ApiErrorCode.SQL_GUARDRAIL_BLOCKED
        return observation.error_code is None

    def _eval_rag_faithful(
        self,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
    ) -> bool | None:
        if not expectation.requires_citation and observation.claim_count == 0:
            return None
        if expectation.requires_citation and observation.evidence_count == 0:
            return False
        return observation.unsupported_claim_count == 0

    def _eval_case_id(self, index: int) -> str:
        return f"case_{index:03d}"

    def _benchmark_expectations(
        self,
        questions: tuple[str, ...],
    ) -> dict[str, BenchmarkExpectation]:
        return {
            question: BenchmarkExpectation(
                expected_tables=() if self._is_dangerous_sql_question(question) else ("revenue_by_month",),
                expected_fields=() if self._is_dangerous_sql_question(question) else ("month", "revenue"),
                dangerous_sql=self._is_dangerous_sql_question(question),
                requires_citation=self._requires_citation(question),
            )
            for question in questions
        }

    def _is_dangerous_sql_question(self, question: str) -> bool:
        stripped_question = question.strip()
        first_word = stripped_question.split(maxsplit=1)[0].lower() if stripped_question else ""
        return first_word in {"drop", "delete", "update", "insert", "alter", "truncate"}

    def _default_eval_questions(self) -> tuple[str, ...]:
        return (
            "Show revenue trend.",
            "Show monthly revenue.",
            "DROP TABLE orders",
        )

    def _requires_citation(self, question: str) -> bool:
        normalized = question.strip().lower()
        return any(keyword in normalized for keyword in ("why", "reason", "cause", "explain"))
