import pytest

from chatbi.frontend.observability import (
    FrontendEventName,
    FrontendLogger,
    InMemoryFrontendLogStore,
)


def test_frontend_logger_records_query_submit_required_fields() -> None:
    store = InMemoryFrontendLogStore()
    logger = FrontendLogger(store=store)

    record = logger.record_query_submitted(
        request_id="req_12345678",
        session_id="s_001",
        trace_id="trc_12345678",
        user_id="u_001",
    )

    assert record.event is FrontendEventName.QUERY_SUBMITTED
    assert record.request_id == "req_12345678"
    assert record.session_id == "s_001"
    assert record.trace_id == "trc_12345678"
    assert record.route == "/api/v1/chat/query"
    assert record.duration_ms is None
    assert record.status is None
    assert store.list_all() == (record,)


def test_frontend_logger_records_api_latency() -> None:
    store = InMemoryFrontendLogStore()
    logger = FrontendLogger(store=store)

    record = logger.record_api_request_completed(
        request_id="req_12345678",
        session_id="s_001",
        trace_id="trc_12345678",
        user_id="u_001",
        route="/api/v1/chat/query",
        duration_ms=12.5,
        status="succeeded",
    )

    assert record.event is FrontendEventName.API_REQUEST_COMPLETED
    assert record.duration_ms == 12.5
    assert record.status == "succeeded"
    assert record.error_code is None
    assert store.list_all() == (record,)


def test_frontend_logger_records_frontend_exception() -> None:
    logger = FrontendLogger()

    record = logger.record_frontend_exception(
        request_id="req_12345678",
        session_id="s_001",
        trace_id="trc_12345678",
        user_id="u_001",
        route="/chat",
        message="Chart renderer failed.",
        error_code="CHART_RENDER_FAILED",
    )

    assert record.event is FrontendEventName.FRONTEND_EXCEPTION
    assert record.status == "failed"
    assert record.error_code == "CHART_RENDER_FAILED"
    assert record.message == "Chart renderer failed."


def test_frontend_logger_rejects_missing_required_fields() -> None:
    logger = FrontendLogger()

    with pytest.raises(ValueError, match="request_id is required"):
        logger.record_query_submitted(
            request_id=" ",
            session_id="s_001",
            trace_id="trc_12345678",
            user_id="u_001",
        )


def test_frontend_logger_rejects_negative_api_latency() -> None:
    logger = FrontendLogger()

    with pytest.raises(ValueError, match="duration_ms"):
        logger.record_api_request_completed(
            request_id="req_12345678",
            session_id="s_001",
            trace_id="trc_12345678",
            user_id="u_001",
            route="/api/v1/chat/query",
            duration_ms=-1,
            status="succeeded",
        )
