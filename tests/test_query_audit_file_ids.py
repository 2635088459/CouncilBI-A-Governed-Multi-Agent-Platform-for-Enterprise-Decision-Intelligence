from datetime import datetime, timezone

from chatbi.governance.query_audit import QueryAuditLog, QueryAuditRecord


class _FakeCursor:
    def fetchone(self) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> _FakeCursor:
        self.commands.append((sql, tuple(params)))
        return _FakeCursor()

    def commit(self) -> None:
        self.commits += 1


def test_save_serializes_file_ids_used_as_a_plain_list_for_jsonb() -> None:
    connection = _FakeConnection()
    log = QueryAuditLog(connection)
    record = QueryAuditRecord(
        trace_id="tr_1",
        request_id="req_1",
        user_id="u_1",
        session_id="ses_1",
        role="analyst",
        question="What is my forecast revenue?",
        file_ids_used=("ufile_abc123",),
    )

    log.save(record)

    sql, params = connection.commands[-1]
    assert "file_ids_used" in sql
    jsonb_params = [p for p in params if hasattr(p, "obj")]
    assert any(p.obj == ["ufile_abc123"] for p in jsonb_params)


def test_save_writes_none_when_no_files_were_used() -> None:
    connection = _FakeConnection()
    log = QueryAuditLog(connection)
    record = QueryAuditRecord(
        trace_id="tr_2",
        request_id="req_2",
        user_id="u_1",
        session_id="ses_1",
        role="analyst",
        question="What was total revenue last month?",
    )

    log.save(record)

    _sql, params = connection.commands[-1]
    assert None in params


def test_row_to_record_round_trips_file_ids_used() -> None:
    now = datetime.now(timezone.utc)
    row = (
        "tr_1", "req_1", "u_1", "org_1", "ses_1", "analyst", "question?",
        "answer", "succeeded", None, False,
        None, None, False,
        10, None, ["ufile_abc123", "ufile_def456"], now, now,
    )

    record = QueryAuditLog._row_to_record(row)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert record.file_ids_used == ("ufile_abc123", "ufile_def456")


def test_row_to_record_treats_null_file_ids_used_as_none() -> None:
    now = datetime.now(timezone.utc)
    row = (
        "tr_1", "req_1", "u_1", "org_1", "ses_1", "analyst", "question?",
        "answer", "succeeded", None, False,
        None, None, False,
        10, None, None, now, now,
    )

    record = QueryAuditLog._row_to_record(row)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert record.file_ids_used is None


def test_to_dict_exposes_file_ids_used_as_a_list() -> None:
    record = QueryAuditRecord(
        trace_id="tr_1",
        request_id="req_1",
        user_id="u_1",
        session_id="ses_1",
        role="analyst",
        question="Compare my forecast with actuals.",
        file_ids_used=("ufile_abc123",),
    )

    assert record.to_dict()["file_ids_used"] == ["ufile_abc123"]
