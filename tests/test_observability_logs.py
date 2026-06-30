from chatbi.observability_logs import (
    InMemoryObservabilityLogStore,
    LogLevel,
    LogSanitizer,
    ObservabilityLogger,
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
