from datetime import datetime, timedelta, timezone

from chatbi.observability import (
    AlertEvaluator,
    AlertRuleId,
    RuntimeRequestSample,
)


NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def test_e2e_error_rate_over_two_percent_for_ten_minutes_fires_alert() -> None:
    samples = tuple(
        RuntimeRequestSample(
            trace_id=f"trc_error_{index}",
            endpoint="/api/v1/chat/query",
            status_code=500 if index < 3 else 200,
            latency_ms=120,
            occurred_at=NOW - timedelta(minutes=5),
        )
        for index in range(100)
    )

    alerts = AlertEvaluator().evaluate(samples=samples, now=NOW)

    assert len(alerts) == 1
    assert alerts[0].rule_id is AlertRuleId.E2E_ERROR_RATE
    assert alerts[0].observed_value == 0.03
    assert alerts[0].threshold == 0.02
    assert alerts[0].window_minutes == 10


def test_e2e_error_rate_equal_to_two_percent_does_not_fire_alert() -> None:
    samples = tuple(
        RuntimeRequestSample(
            trace_id=f"trc_ok_threshold_{index}",
            endpoint="/api/v1/chat/query",
            status_code=500 if index < 2 else 200,
            latency_ms=120,
            occurred_at=NOW - timedelta(minutes=5),
        )
        for index in range(100)
    )

    alerts = AlertEvaluator().evaluate(samples=samples, now=NOW)

    assert not alerts


def test_chat_query_p95_latency_over_eight_seconds_for_fifteen_minutes_fires_alert() -> None:
    samples = tuple(
        RuntimeRequestSample(
            trace_id=f"trc_slow_{index}",
            endpoint="/api/v1/chat/query",
            status_code=200,
            latency_ms=9000 if index >= 18 else 100,
            occurred_at=NOW - timedelta(minutes=7),
        )
        for index in range(20)
    )

    alerts = AlertEvaluator().evaluate(samples=samples, now=NOW)

    assert len(alerts) == 1
    assert alerts[0].rule_id is AlertRuleId.CHAT_QUERY_P95_LATENCY
    assert alerts[0].observed_value > 8000
    assert alerts[0].window_minutes == 15


def test_alert_evaluator_ignores_samples_outside_rule_window() -> None:
    samples = tuple(
        RuntimeRequestSample(
            trace_id=f"trc_old_error_{index}",
            endpoint="/api/v1/chat/query",
            status_code=500,
            latency_ms=120,
            occurred_at=NOW - timedelta(minutes=30),
        )
        for index in range(100)
    )

    alerts = AlertEvaluator().evaluate(samples=samples, now=NOW)

    assert not alerts


def test_alert_evaluator_requires_minimum_sample_count_to_reduce_noise() -> None:
    samples = tuple(
        RuntimeRequestSample(
            trace_id=f"trc_tiny_{index}",
            endpoint="/api/v1/chat/query",
            status_code=500,
            latency_ms=9000,
            occurred_at=NOW - timedelta(minutes=1),
        )
        for index in range(3)
    )

    alerts = AlertEvaluator().evaluate(samples=samples, now=NOW)

    assert not alerts


def test_slo_statuses_show_active_rule_health_for_dashboard() -> None:
    samples = tuple(
        RuntimeRequestSample(
            trace_id=f"trc_dashboard_{index}",
            endpoint="/api/v1/chat/query",
            status_code=200,
            latency_ms=100,
            occurred_at=NOW - timedelta(minutes=1),
        )
        for index in range(20)
    )

    statuses = AlertEvaluator().slo_statuses(samples=samples, now=NOW)

    assert {status.rule_id for status in statuses} == {
        AlertRuleId.E2E_ERROR_RATE,
        AlertRuleId.CHAT_QUERY_P95_LATENCY,
    }
    assert all(status.passing for status in statuses)
    assert all(status.sample_count == 20 for status in statuses)
