"""Shared building blocks for ``FileDataAgent`` and ``FederatedQueryAgent``.

Both agents need the same three things: verify a requested file belongs to
the requester and is ready, register a file's Parquet snapshot as a named
DuckDB view, and detect a write statement before it ever reaches DuckDB.
Factored out here so the two agents cannot drift into subtly different
security checks.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

import duckdb

from chatbi.files.contracts import UserUploadedFile
from chatbi.files.repository import FileRepository
from chatbi.files.storage import ObjectStorageAdapter, parquet_storage_key


_BLOCKED_STATEMENT_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE)\b",
    re.IGNORECASE,
)

DEFAULT_QUERY_MEMORY_LIMIT = "2GB"


class FileOwnershipError(Exception):
    """Raised when a requested file_id does not belong to the requesting user."""


class FileNotReadyError(Exception):
    """Raised when a requested file's status is not 'ready'."""


class InvalidGeneratedSqlError(Exception):
    """Raised when the LLM-generated SQL is not valid DuckDB SQL.

    The LLM is asked to answer with SQL only, but a real model can still
    reply with prose (e.g. "To answer that I would need historical
    revenue..."). DuckDB's parser/binder rejects that at execution time;
    wrapping it here gives the agents a typed error to respond to
    gracefully instead of letting an uncaught duckdb exception reach the
    HTTP layer as a bare 500.
    """


class QueryResourceExceededError(Exception):
    """Raised when a query exceeds the configured DuckDB memory budget.

    NFR-FV10-008: this bounds the *common* case where DuckDB's own tracked
    buffer manager notices the overrun (aggregations, sorts, joins that spill
    through its allocator) and raises ``duckdb.OutOfMemoryException``
    instead of letting the process's RSS grow unchecked. It is not a full
    guarantee: a query shape that allocates very large amounts of memory in
    one uninterruptible step (e.g. an enormous unfiltered cross join) can
    still be killed by the OS before DuckDB's own check fires. Closing that
    gap for good needs the query to run in an isolated subprocess rather than
    in-process, which is future work, not something this guard alone fixes.
    """


def apply_memory_limit(connection: Any, memory_limit: str = DEFAULT_QUERY_MEMORY_LIMIT) -> None:
    connection.execute(f"SET memory_limit='{memory_limit}'")


def fetch_table(connection: Any, sql_text: str) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    """Run ``sql_text`` and materialize it, translating DuckDB OOM into our own error."""

    try:
        relation = connection.sql(sql_text)
        columns = tuple(relation.columns)
        rows = tuple(dict(zip(columns, row, strict=True)) for row in relation.fetchall())
    except duckdb.OutOfMemoryException as exc:
        raise QueryResourceExceededError(str(exc)) from exc
    except duckdb.Error as exc:
        raise InvalidGeneratedSqlError(str(exc)) from exc
    return columns, rows


def load_ready_owned_file(
    repository: FileRepository,
    file_id: str,
    user_id: str,
) -> UserUploadedFile:
    file = repository.get(file_id)
    if file is None or file.user_id != user_id:
        raise FileOwnershipError(file_id)
    if file.status != "ready":
        raise FileNotReadyError(file_id)
    return file


def split_file_ids_by_type(
    file_ids: tuple[str, ...],
    files_by_id: Mapping[str, UserUploadedFile],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Spec FV10.6 FR-FV10-064: (structured_file_ids, unstructured_file_ids).

    Preserves each subset's relative order from ``file_ids``. Every id in
    ``file_ids`` MUST already be a key in ``files_by_id`` — this function
    does not perform the ownership/readiness screening FR-FV10-069 requires
    to have already happened (``_validate_chat_query_file_ids`` in http.py).
    """

    structured = tuple(fid for fid in file_ids if files_by_id[fid].schema_json is not None)
    unstructured = tuple(fid for fid in file_ids if files_by_id[fid].schema_json is None)
    return structured, unstructured


# 10-followups/08: a purely-structured file selection forces every question
# through FileDataAgent/FederatedQueryAgent, which have no graceful "this
# isn't about your file" output — the LLM either invents a plausible-looking
# mapping onto the wrong columns, or writes SQL that doesn't bind, and either
# way the request never reaches the main orchestrator's real business tables
# that could have actually answered it. This is a best-effort, no-LLM-call
# relevance gate applied before committing to the file branch at all.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "what", "which", "who",
        "whom", "this", "that", "these", "those", "it", "its", "about",
        "and", "or", "but", "to", "of", "in", "on", "at", "by", "for",
        "from", "with", "my", "our", "your", "please", "show", "me",
        "give", "tell", "one", "ones", "did", "do", "does", "will",
        "would", "can", "could", "should", "just", "only", "really",
        "actually", "also", "even",
    }
)

# A question sharing only a quarter/half/year token with a file name (e.g.
# both mention "H1 2026") is not meaningfully about that file — these are
# too generic to count as a relevance signal on their own.
_GENERIC_DATE_TOKEN = re.compile(r"^(?:\d+|h[12]|q[1-4])$", re.IGNORECASE)

# Same reasoning for a literal month name: "and June?" following a question
# about a file whose own month values are formatted "2026-06" shares no
# literal value with that file, but is exactly the kind of short follow-up
# Spec FV10.4 relies on conversation-history injection (not this gate) to
# resolve. The column name "month" itself is deliberately NOT in this list —
# that is a real, specific schema match, not a coincidental one.
_MONTH_NAME_TOKEN = re.compile(
    r"^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)$",
    re.IGNORECASE,
)

_FILE_REFERENCE_HINTS = frozenset(
    {"file", "files", "uploaded", "upload", "attached", "attachment", "csv", "spreadsheet", "dataset", "xlsx"}
)


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def _content_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _tokenize(text)
        if token not in _STOPWORDS
        and not _GENERIC_DATE_TOKEN.match(token)
        and not _MONTH_NAME_TOKEN.match(token)
    )


def question_references_attached_file(question: str, file: UserUploadedFile) -> bool:
    """Best-effort: does ``question`` plausibly concern ``file`` at all?

    Used only to keep FileDataAgent/FederatedQueryAgent from being invoked
    against a structured file whose schema has nothing to do with the
    question — never to block a genuine follow-up. A question with too few
    content words to judge (e.g. "What about this one?") is treated as
    relevant by default: resolving that kind of question is exactly what
    conversation-history injection (Spec FV10.4) already exists to do, and
    this function has no access to that history.
    """

    if _tokenize(question) & _FILE_REFERENCE_HINTS:
        return True

    question_tokens = _content_tokens(question)
    if not question_tokens:
        return True

    file_tokens = _content_tokens(file.original_name)
    if file.schema_json is not None:
        for column in file.schema_json["columns"]:
            file_tokens |= _content_tokens(str(column["name"]))

    return bool(question_tokens & file_tokens)


def question_references_any_attached_file(
    question: str, files: tuple[UserUploadedFile, ...]
) -> bool:
    """Routing-level gate: at least one attached file is relevant, or at
    least one is unstructured (its own relevance is FileScopedRetriever's
    job, not this function's — see 10-followups/06)."""

    if not files:
        return False
    if any(file.schema_json is None for file in files):
        return True
    return any(question_references_attached_file(question, file) for file in files)


def find_blocked_statement(sql_text: str) -> str | None:
    """Return the offending keyword (e.g. ``"UPDATE"``) or ``None`` if the SQL is read-only."""

    match = _BLOCKED_STATEMENT_PATTERN.search(sql_text)
    if match is None:
        return None
    return match.group(1).upper()


def register_file_parquet_view(connection: Any, storage: ObjectStorageAdapter, file: UserUploadedFile) -> Path:
    """Download a file's Parquet snapshot and register it as ``file_{file_id}``.

    Returns the temp file path so the caller can clean it up once the
    connection using it is done (DuckDB reads Parquet lazily per query, so
    the file must outlive query execution, not just view creation).
    """

    parquet_bytes = storage.get_object(parquet_storage_key(file.storage_key))
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_file.write(parquet_bytes)
        temp_path = Path(temp_file.name)
    # DuckDB does not support prepared parameters inside CREATE VIEW;
    # temp_path is a locally generated tempfile path, not user input.
    connection.execute(
        f'CREATE VIEW "file_{file.file_id}" AS SELECT * FROM read_parquet(\'{temp_path}\')'
    )
    return temp_path
