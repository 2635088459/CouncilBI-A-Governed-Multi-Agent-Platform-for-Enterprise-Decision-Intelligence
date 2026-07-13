from chatbi.history.in_memory import (
    InMemoryQueryHistory,
    conversation_context_text,
    conversation_messages,
)
from chatbi.core.contracts import (
    ErrorCode,
    Locale,
    QueryAnswer,
    QueryHistoryRecord,
    QueryHistoryStatus,
    QueryRequest,
    TableResult,
    UserRole,
    new_trace_id,
)


def make_request(question: str = "Show revenue trend.", session_id: str = "s_001") -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id=session_id,
        question=question,
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def make_answer(trace_id: str, answer_text: str = "Revenue is up.") -> QueryAnswer:
    return QueryAnswer(
        answer_text=answer_text,
        sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 10",
        table_result=TableResult(columns=("month", "revenue"), rows=()),
        trace_id=trace_id,
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


def test_list_by_session_returns_the_5_most_recent_records_oldest_first() -> None:
    # TC-FV10-137
    store = InMemoryQueryHistory()
    records: list[QueryHistoryRecord] = []
    for index in range(8):
        trace_id = f"trc_turn_{index}"
        record = QueryHistoryRecord(
            trace_id=trace_id,
            request=make_request(f"Question {index}", session_id="ses_1"),
            answer=make_answer(trace_id),
        )
        records.append(record)
        store.save(record)

    result = store.list_by_session("ses_1", limit=5)

    assert [record.request.question for record in result] == [
        "Question 3",
        "Question 4",
        "Question 5",
        "Question 6",
        "Question 7",
    ]


def test_list_by_session_returns_empty_tuple_for_a_session_with_no_records() -> None:
    # TC-FV10-138
    store = InMemoryQueryHistory()

    assert store.list_by_session("ses_missing") == ()


def test_list_by_session_never_returns_a_different_sessions_record() -> None:
    # TC-FV10-139
    store = InMemoryQueryHistory()
    own_record = QueryHistoryRecord(
        trace_id="trc_own",
        request=make_request("Show revenue.", session_id="ses_a"),
        answer=make_answer("trc_own"),
    )
    other_record = QueryHistoryRecord(
        trace_id="trc_other",
        request=make_request("Show refunds.", session_id="ses_b"),
        answer=make_answer("trc_other"),
    )
    store.save(own_record)
    store.save(other_record)

    result = store.list_by_session("ses_a")

    assert result == (own_record,)


def test_conversation_messages_alternates_user_and_assistant_oldest_first() -> None:
    # TC-FV10-140
    records = tuple(
        QueryHistoryRecord(
            trace_id=f"trc_{index}",
            request=make_request(f"Question {index}", session_id="ses_1"),
            answer=make_answer(f"trc_{index}", f"Answer {index}"),
        )
        for index in range(3)
    )

    messages = conversation_messages(records)

    assert messages == (
        {"role": "user", "content": "Question 0"},
        {"role": "assistant", "content": "Answer 0"},
        {"role": "user", "content": "Question 1"},
        {"role": "assistant", "content": "Answer 1"},
        {"role": "user", "content": "Question 2"},
        {"role": "assistant", "content": "Answer 2"},
    )


def test_conversation_messages_is_empty_for_no_records() -> None:
    assert conversation_messages(()) == ()


def test_conversation_context_text_joins_questions_and_answers() -> None:
    records = (
        QueryHistoryRecord(
            trace_id="trc_1",
            request=make_request("Why did revenue drop?", session_id="ses_1"),
            answer=make_answer("trc_1", "Campaign spend paused."),
        ),
    )

    assert conversation_context_text(records) == "Why did revenue drop? Campaign spend paused."
