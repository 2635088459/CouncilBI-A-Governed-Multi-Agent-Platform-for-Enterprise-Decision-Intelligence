from chatbi.history.in_memory import InMemoryQueryHistory
from chatbi.core.contracts import (
    ErrorCode,
    Locale,
    QueryHistoryRecord,
    QueryHistoryStatus,
    QueryRequest,
    UserRole,
    new_trace_id,
)


def make_request(question: str = "Show revenue trend.") -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question=question,
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def test_history_saves_and_replays_record_by_trace_id() -> None:
    store = InMemoryQueryHistory()
    trace_id = new_trace_id()
    record = QueryHistoryRecord(
        trace_id=trace_id,
        request=make_request(),
        answer=None,
    )

    store.save(record)

    assert store.get(trace_id) == record


def test_history_returns_none_for_unknown_trace_id() -> None:
    store = InMemoryQueryHistory()

    assert store.get("trc_missing") is None


def test_history_preserves_failed_requests_for_audit_and_replay() -> None:
    store = InMemoryQueryHistory()
    trace_id = new_trace_id()
    record = QueryHistoryRecord(
        trace_id=trace_id,
        request=make_request("DROP TABLE orders"),
        answer=None,
        failed_error_code=ErrorCode.SQL_DENY_STATEMENT,
    )

    store.save(record)
    replayed = store.get(trace_id)

    assert replayed is not None
    assert replayed.request.question == "DROP TABLE orders"
    assert replayed.failed_error_code is ErrorCode.SQL_DENY_STATEMENT
    assert replayed.status is QueryHistoryStatus.FAILED


def test_history_lists_all_saved_records() -> None:
    store = InMemoryQueryHistory()
    first = QueryHistoryRecord(
        trace_id=new_trace_id(),
        request=make_request("Show revenue."),
        answer=None,
    )
    second = QueryHistoryRecord(
        trace_id=new_trace_id(),
        request=make_request("Show refunds."),
        answer=None,
    )

    store.save(first)
    store.save(second)

    assert store.list_all() == (first, second)


def test_history_filters_records_by_status() -> None:
    store = InMemoryQueryHistory()
    succeeded = QueryHistoryRecord(
        trace_id=new_trace_id(),
        request=make_request("Show revenue."),
        answer=None,
    )
    failed = QueryHistoryRecord(
        trace_id=new_trace_id(),
        request=make_request("DROP TABLE orders"),
        answer=None,
        failed_error_code=ErrorCode.SQL_DENY_STATEMENT,
    )

    store.save(succeeded)
    store.save(failed)

    assert store.list_by_status(QueryHistoryStatus.SUCCEEDED) == (succeeded,)
    assert store.list_by_status(QueryHistoryStatus.FAILED) == (failed,)
