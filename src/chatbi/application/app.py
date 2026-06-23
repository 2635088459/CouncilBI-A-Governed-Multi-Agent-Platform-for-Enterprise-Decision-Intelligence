"""Application entry points for the Backend API slice."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
    datasets_catalog_payload,
    envelope,
    error_envelope,
    history_item_payload,
    metrics_catalog_payload,
    observability_trace_payload,
    quality_dashboard_payload,
    success_envelope,
    to_chat_query_response,
    trace_detail_payload,
    utc_now_iso,
)
from chatbi.core.contracts import Locale, QueryAnswer, QueryRequest, UserRole, new_trace_id
from chatbi.core.contracts import utc_now
from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog
from chatbi.evaluation import BenchmarkExpectation, EvaluationObservation, EvaluationScorer
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
        trace_recorder: TraceRecorder | None = None,
        observability_logger: ObservabilityLogger | None = None,
    ) -> None:
        self._orchestrator = orchestrator or SimpleOrchestrator()
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()
        self._rate_limit_per_minute = rate_limit_per_minute
        self._rate_limit_events: dict[str, list[float]] = {}
        self._idempotency_cache: dict[tuple[str, str], _IdempotencyCacheEntry] = {}
        self._audit_records: list[ApiAuditRecord] = []
        self._evaluation_scorer = EvaluationScorer()
        self._trace_recorder = trace_recorder or TraceRecorder()
        self._alert_evaluator = AlertEvaluator()
        self._runtime_samples: list[RuntimeRequestSample] = []
        self._latest_eval_result: EvalRunResultPayload | None = None
        self._observability_logger = observability_logger or ObservabilityLogger()

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
    ) -> ApiEnvelope:
        active_trace_id = trace_id or new_trace_id()
        started_at = monotonic()
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
            return cached

        request = payload.to_domain()
        self._trace_recorder.record(
            trace_id=active_trace_id,
            span_name=TraceSpanName.ORCHESTRATION_PLANNED,
            attributes={"idempotency_key_present": idempotency_key is not None},
        )
        answer = self._orchestrator.answer(request, trace_id=active_trace_id)
        self._record_answer_spans(answer)
        response = to_chat_query_response(answer)
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
        return response_envelope

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
            self._orchestrator.history.list_all(),
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
        if record is None:
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
        response = envelope(
            data={
                "trace_id": payload.trace_id,
                "completed": payload.completed,
                "spans": payload.spans,
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

    def handle_quality_dashboard(self, user_id: str, trace_id: str) -> ApiEnvelope:
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
            latest_eval_result=self._latest_eval_result,
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
        result = self._evaluation_scorer.score_suite(
            eval_suite_id=payload.eval_suite_id,
            observations=observations,
            expectations=self._benchmark_expectations(questions),
        )
        self._latest_eval_result = result
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
    ) -> ApiEnvelope | None:
        if self._rate_limit_per_minute <= 0:
            return None

        now = monotonic()
        recent_events = [
            event_time
            for event_time in self._rate_limit_events.get(user_id, [])
            if now - event_time < 60
        ]
        if len(recent_events) >= self._rate_limit_per_minute:
            response = error_envelope(
                code=ApiErrorCode.RATE_LIMITED,
                message="Too many requests for this user. Please retry later.",
                trace_id=trace_id,
                data={"retry_after_seconds": 60},
            )
            self._audit(
                trace_id=trace_id,
                user_id=user_id,
                endpoint=endpoint,
                status_code=429,
                error_code=ApiErrorCode.RATE_LIMITED,
            )
            self._rate_limit_events[user_id] = recent_events
            return response

        recent_events.append(now)
        self._rate_limit_events[user_id] = recent_events
        return None

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
