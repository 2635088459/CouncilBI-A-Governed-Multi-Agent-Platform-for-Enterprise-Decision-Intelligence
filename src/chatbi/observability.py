"""Online SLO monitoring and alert evaluation for spec 10.

This module is the smoke alarm for runtime quality. It does not store metrics
or send pages; it only decides whether recent request samples violate an alert
rule for long enough to matter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from time import perf_counter
from statistics import quantiles
from typing import Any, Mapping, TypeVar

from chatbi.core.contracts import utc_now


T = TypeVar("T")


def _empty_attributes() -> Mapping[str, Any]:
    return {}


class AlertRuleId(StrEnum):
    E2E_ERROR_RATE = "e2e_error_rate"
    CHAT_QUERY_P95_LATENCY = "chat_query_p95_latency"


class AlertSeverity(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class TraceSpanName(StrEnum):
    REQUEST_RECEIVED = "request_received"
    ORCHESTRATION_PLANNED = "orchestration_planned"
    SQL_GENERATED = "sql_generated"
    SQL_GUARDRAIL_CHECKED = "sql_guardrail_checked"
    RAG_RETRIEVED = "rag_retrieved"
    ANALYTICS_DONE = "analytics_done"
    VERIFIER_DONE = "verifier_done"
    RESPONSE_SENT = "response_sent"


class TraceSpanStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeRequestSample:
    """One completed API request as seen by monitoring."""

    trace_id: str
    endpoint: str
    status_code: int
    latency_ms: int
    occurred_at: datetime

    @property
    def succeeded(self) -> bool:
        return 200 <= self.status_code < 400


@dataclass(frozen=True, slots=True)
class AlertRule:
    rule_id: AlertRuleId
    endpoint: str
    threshold: float
    window: timedelta
    severity: AlertSeverity
    min_sample_count: int = 20


@dataclass(frozen=True, slots=True)
class AlertEvent:
    rule_id: AlertRuleId
    endpoint: str
    severity: AlertSeverity
    observed_value: float
    threshold: float
    window_minutes: int
    sample_count: int
    message: str


@dataclass(frozen=True, slots=True)
class SloStatus:
    rule_id: AlertRuleId
    endpoint: str
    target: float
    observed_value: float
    passing: bool
    sample_count: int


@dataclass(frozen=True, slots=True)
class ObservabilitySpan:
    """One standard trace span for a request."""

    trace_id: str
    span_name: TraceSpanName
    status: TraceSpanStatus
    occurred_at: datetime = field(default_factory=utc_now)
    duration_ms: int | None = None
    attributes: Mapping[str, Any] = field(default_factory=_empty_attributes)

    def __post_init__(self) -> None:
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("duration_ms must be greater than or equal to 0")


@dataclass(frozen=True, slots=True)
class TraceReplay:
    trace_id: str
    spans: tuple[ObservabilitySpan, ...]

    @property
    def completed(self) -> bool:
        span_names = {span.span_name for span in self.spans}
        return (
            TraceSpanName.REQUEST_RECEIVED in span_names
            and TraceSpanName.RESPONSE_SENT in span_names
        )


class InMemoryObservabilityStore:
    """Small synchronous trace store for local runtime and tests."""

    def __init__(self) -> None:
        self._spans: list[ObservabilitySpan] = []

    def add_span(self, span: ObservabilitySpan) -> None:
        self._spans.append(span)

    def list_spans(self, trace_id: str) -> tuple[ObservabilitySpan, ...]:
        return tuple(span for span in self._spans if span.trace_id == trace_id)

    def replay(self, trace_id: str) -> TraceReplay | None:
        spans = self.list_spans(trace_id)
        if not spans:
            return None
        return TraceReplay(trace_id=trace_id, spans=spans)

    def list_all(self) -> tuple[ObservabilitySpan, ...]:
        return tuple(self._spans)


class TraceRecorder:
    """Write standard spans with tiny synchronous overhead."""

    def __init__(self, store: InMemoryObservabilityStore | None = None) -> None:
        self._store = store or InMemoryObservabilityStore()

    @property
    def store(self) -> InMemoryObservabilityStore:
        return self._store

    def record(
        self,
        trace_id: str,
        span_name: TraceSpanName,
        status: TraceSpanStatus = TraceSpanStatus.SUCCEEDED,
        duration_ms: int | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> ObservabilitySpan:
        active_attributes: Mapping[str, Any] = attributes if attributes is not None else {}
        span = ObservabilitySpan(
            trace_id=trace_id,
            span_name=span_name,
            status=status,
            duration_ms=duration_ms,
            attributes=active_attributes,
        )
        self._store.add_span(span)
        return span

    def run_span(
        self,
        trace_id: str,
        span_name: TraceSpanName,
        action: Callable[[], T],
        attributes: Mapping[str, Any] | None = None,
    ) -> T:
        started_at = perf_counter()
        try:
            result = action()
        except Exception:
            self.record(
                trace_id=trace_id,
                span_name=span_name,
                status=TraceSpanStatus.FAILED,
                duration_ms=self._duration_ms(started_at),
                attributes=attributes,
            )
            raise

        self.record(
            trace_id=trace_id,
            span_name=span_name,
            status=TraceSpanStatus.SUCCEEDED,
            duration_ms=self._duration_ms(started_at),
            attributes=attributes,
        )
        return result

    def _duration_ms(self, started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))


class AlertEvaluator:
    """Evaluate online samples against the spec's alert rules."""

    def __init__(self, rules: tuple[AlertRule, ...] | None = None) -> None:
        self._rules = rules or default_alert_rules()

    def evaluate(
        self,
        samples: tuple[RuntimeRequestSample, ...],
        now: datetime,
    ) -> tuple[AlertEvent, ...]:
        alerts: list[AlertEvent] = []
        for rule in self._rules:
            window_samples = self._window_samples(
                samples=samples,
                endpoint=rule.endpoint,
                now=now,
                window=rule.window,
            )
            if len(window_samples) < rule.min_sample_count:
                continue

            observed_value = self._observed_value(rule.rule_id, window_samples)
            if observed_value > rule.threshold:
                alerts.append(
                    AlertEvent(
                        rule_id=rule.rule_id,
                        endpoint=rule.endpoint,
                        severity=rule.severity,
                        observed_value=observed_value,
                        threshold=rule.threshold,
                        window_minutes=int(rule.window.total_seconds() // 60),
                        sample_count=len(window_samples),
                        message=self._message(rule, observed_value),
                    )
                )
        return tuple(alerts)

    def slo_statuses(
        self,
        samples: tuple[RuntimeRequestSample, ...],
        now: datetime,
    ) -> tuple[SloStatus, ...]:
        statuses: list[SloStatus] = []
        for rule in self._rules:
            window_samples = self._window_samples(
                samples=samples,
                endpoint=rule.endpoint,
                now=now,
                window=rule.window,
            )
            observed_value = self._observed_value(rule.rule_id, window_samples)
            statuses.append(
                SloStatus(
                    rule_id=rule.rule_id,
                    endpoint=rule.endpoint,
                    target=rule.threshold,
                    observed_value=observed_value,
                    passing=observed_value <= rule.threshold,
                    sample_count=len(window_samples),
                )
            )
        return tuple(statuses)

    def _window_samples(
        self,
        samples: tuple[RuntimeRequestSample, ...],
        endpoint: str,
        now: datetime,
        window: timedelta,
    ) -> tuple[RuntimeRequestSample, ...]:
        window_start = now - window
        return tuple(
            sample
            for sample in samples
            if sample.endpoint == endpoint
            and window_start <= sample.occurred_at <= now
        )

    def _observed_value(
        self,
        rule_id: AlertRuleId,
        samples: tuple[RuntimeRequestSample, ...],
    ) -> float:
        if rule_id is AlertRuleId.E2E_ERROR_RATE:
            return self._error_rate(samples)
        if rule_id is AlertRuleId.CHAT_QUERY_P95_LATENCY:
            return float(self._p95_latency_ms(samples))
        raise ValueError(f"Unsupported alert rule {rule_id}.")

    def _error_rate(self, samples: tuple[RuntimeRequestSample, ...]) -> float:
        if not samples:
            return 0.0
        failed_count = sum(1 for sample in samples if not sample.succeeded)
        return round(failed_count / len(samples), 4)

    def _p95_latency_ms(self, samples: tuple[RuntimeRequestSample, ...]) -> int:
        if not samples:
            return 0
        latencies = sorted(sample.latency_ms for sample in samples)
        if len(latencies) == 1:
            return latencies[0]
        return int(quantiles(latencies, n=100, method="inclusive")[94])

    def _message(self, rule: AlertRule, observed_value: float) -> str:
        if rule.rule_id is AlertRuleId.E2E_ERROR_RATE:
            percent = round(observed_value * 100, 2)
            threshold_percent = round(rule.threshold * 100, 2)
            return f"E2E error rate is {percent}% over threshold {threshold_percent}%."
        return f"/chat/query P95 latency is {int(observed_value)}ms over threshold {int(rule.threshold)}ms."


def default_alert_rules() -> tuple[AlertRule, ...]:
    return (
        AlertRule(
            rule_id=AlertRuleId.E2E_ERROR_RATE,
            endpoint="/api/v1/chat/query",
            threshold=0.02,
            window=timedelta(minutes=10),
            severity=AlertSeverity.P1,
        ),
        AlertRule(
            rule_id=AlertRuleId.CHAT_QUERY_P95_LATENCY,
            endpoint="/api/v1/chat/query",
            threshold=8000,
            window=timedelta(minutes=15),
            severity=AlertSeverity.P2,
        ),
    )
