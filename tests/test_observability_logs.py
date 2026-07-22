import json
from datetime import datetime, timedelta, timezone

from chatbi.observability_logs import (
    InMemoryObservabilityLogStore,
    LogLevel,
    LogSanitizer,
    ObservabilityLogger,
    ObservabilityLogRecord,
    render_observability_json_log,
    render_observability_json_logs,
)


def test_log_sanitizer_masks_email_and_phone_in_message() -> None:
    sanitizer = LogSanitizer()

    message = sanitizer.sanitize_message(
        "Customer alice@example.com called from 408-555-1234."
    )

    assert "alice@example.com" not in message
    assert "408-555-1234" not in message
    assert "[masked-email]" in message
    assert "[masked-phone]" in message


def test_log_sanitizer_masks_sensitive_structured_attributes() -> None:
    sanitizer = LogSanitizer()

    attributes = sanitizer.sanitize_attributes(
        {
            "user_email": "alice@example.com",
            "phone": "408-555-1234",
            "customer_id": "cust_001",
            "safe_metric": "revenue",
            "nested": {
                "customer_name": "Alice Chen",
                "comment": "Reach me at bob@example.com",
            },
        }
    )

    assert attributes["user_email"] == "[masked-email]"
    assert attributes["phone"] == "[masked-phone]"
    assert attributes["customer_id"] == "[masked-customer]"
    assert attributes["safe_metric"] == "revenue"
    assert attributes["nested"]["customer_name"] == "[masked-name]"
    assert attributes["nested"]["comment"] == "Reach me at [masked-email]"


def test_log_sanitizer_masks_passwords_and_tokens_in_messages() -> None:
    sanitizer = LogSanitizer()

    message = sanitizer.sanitize_message(
        "Sign in failed password=correct-horse Authorization: Bearer abc.def.ghi "
        "refresh_token=rfr_plaintext access_token=acc_plaintext secret:open-sesame"
    )

    assert "correct-horse" not in message
    assert "abc.def.ghi" not in message
    assert "rfr_plaintext" not in message
    assert "acc_plaintext" not in message
    assert "open-sesame" not in message
    assert "[masked-token]" in message
    assert "[masked-secret]" in message


def test_log_sanitizer_masks_auth_tokens_in_structured_attributes() -> None:
    sanitizer = LogSanitizer()

    attributes = sanitizer.sanitize_attributes(
        {
            "password": "correct horse battery staple",
            "access_token": "signed.access.token",
            "refresh_token": "rfr_plaintext",
            "authorization": "Bearer signed.access.token",
            "nested": {
                "api_key": "sk_live_secret",
                "safe_metric": "revenue",
            },
        }
    )

    assert attributes["password"] == "[masked-secret]"
    assert attributes["access_token"] == "[masked-secret]"
    assert attributes["refresh_token"] == "[masked-secret]"
    assert attributes["authorization"] == "[masked-secret]"
    assert attributes["nested"]["api_key"] == "[masked-secret]"
    assert attributes["nested"]["safe_metric"] == "revenue"


def test_observability_logger_stores_only_sanitized_records() -> None:
    store = InMemoryObservabilityLogStore()
    logger = ObservabilityLogger(store=store)

    logger.record(
        trace_id="trc_log_sanitized",
        level=LogLevel.INFO,
        message="Received query from alice@example.com",
        endpoint="/api/v1/chat/query",
        user_id="alice@example.com",
        attributes={
            "session_id": "session_123",
            "question": "Show customer 408-555-1234 revenue.",
        },
    )

    record = store.list_by_trace_id("trc_log_sanitized")[0]

    assert record.user_id == "[masked-user]"
    assert "alice@example.com" not in record.message
    assert record.attributes["session_id"] == "[masked-session]"
    assert "408-555-1234" not in record.attributes["question"]


def test_observability_log_store_lists_records_by_trace_id() -> None:
    store = InMemoryObservabilityLogStore()
    logger = ObservabilityLogger(store=store)

    logger.record(
        trace_id="trc_one",
        level=LogLevel.INFO,
        message="one",
        endpoint="/api/v1/chat/query",
        user_id="u_001",
    )
    logger.record(
        trace_id="trc_two",
        level=LogLevel.ERROR,
        message="two",
        endpoint="/api/v1/chat/query",
        user_id="u_002",
    )

    records = store.list_by_trace_id("trc_one")

    assert len(records) == 1
    assert records[0].trace_id == "trc_one"
    assert len(store.list_all()) == 2


def test_observability_log_store_prune_older_than_removes_only_stale_records() -> None:
    # FR-FV03-043: durable storage otherwise grows without bound — a
    # retention sweep (api/http.py) calls this on a schedule.
    store = InMemoryObservabilityLogStore()
    now = datetime.now(timezone.utc)
    store.add(
        ObservabilityLogRecord(
            trace_id="trc_old",
            level=LogLevel.INFO,
            message="old",
            endpoint="/api/v1/chat/query",
            user_id="u_001",
            recorded_at=now - timedelta(days=40),
        )
    )
    store.add(
        ObservabilityLogRecord(
            trace_id="trc_recent",
            level=LogLevel.INFO,
            message="recent",
            endpoint="/api/v1/chat/query",
            user_id="u_001",
            recorded_at=now,
        )
    )

    removed_count = store.prune_older_than(now - timedelta(days=30))

    assert removed_count == 1
    remaining = store.list_all()
    assert len(remaining) == 1
    assert remaining[0].trace_id == "trc_recent"


def test_observability_logger_supports_v2_required_structured_fields() -> None:
    logger = ObservabilityLogger()

    record = logger.record(
        trace_id="tr_12345678",
        level=LogLevel.INFO,
        message="Accepted v2 chat query.",
        endpoint="/api/v2/chat/query",
        user_id="u_001",
        service="chatbi-api",
        event="chat_query_accepted",
        request_id="req_12345678",
    )

    assert record.trace_id == "tr_12345678"
    assert record.request_id == "req_12345678"
    assert record.service == "chatbi-api"
    assert record.event == "chat_query_accepted"
    assert record.level is LogLevel.INFO


def test_observability_log_renders_as_json_with_trace_id() -> None:
    logger = ObservabilityLogger()
    record = logger.record(
        trace_id="trc_json_log",
        level=LogLevel.INFO,
        message="Accepted chat query.",
        endpoint="/api/v1/chat/query",
        user_id="u_001",
        attributes={
            "session_id": "session_123",
            "metric": "revenue",
            "steps": ("received", "answered"),
        },
    )

    json_line = render_observability_json_log(record)
    payload = json.loads(json_line)

    assert payload["trace_id"] == "trc_json_log"
    assert payload["level"] == "info"
    assert payload["endpoint"] == "/api/v1/chat/query"
    assert payload["user_id"] == "[masked-user]"
    assert payload["attributes"]["session_id"] == "[masked-session]"
    assert payload["attributes"]["steps"] == ["received", "answered"]
    assert "recorded_at" in payload


def test_observability_log_renders_multiple_json_lines() -> None:
    logger = ObservabilityLogger()
    first = logger.record(
        trace_id="trc_json_logs",
        level=LogLevel.INFO,
        message="one",
        endpoint="/api/v1/chat/query",
        user_id="u_001",
    )
    second = logger.record(
        trace_id="trc_json_logs",
        level=LogLevel.WARNING,
        message="two",
        endpoint="/api/v1/chat/query",
        user_id="u_001",
    )

    lines = render_observability_json_logs((first, second))

    assert [json.loads(line)["level"] for line in lines] == ["info", "warning"]
