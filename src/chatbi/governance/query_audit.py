"""Persistent audit log for all user chat queries (admin visibility)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence


QUERY_AUDIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chatbi_query_audit_log (
    trace_id        TEXT PRIMARY KEY,
    request_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    org_id          TEXT NOT NULL DEFAULT 'org_legacy',
    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL,
    question        TEXT NOT NULL,
    answer_text     TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    error_code      TEXT,
    blocked         BOOLEAN NOT NULL DEFAULT FALSE,
    sql_row_count   INTEGER,
    rag_doc_count   INTEGER,
    has_chart       BOOLEAN NOT NULL DEFAULT FALSE,
    latency_ms      INTEGER,
    evidence_json   TEXT,
    accepted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_query_audit_user_id
    ON chatbi_query_audit_log (user_id, accepted_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_audit_status
    ON chatbi_query_audit_log (status, accepted_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_audit_accepted_at
    ON chatbi_query_audit_log (accepted_at DESC);
""".strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class QueryAuditRecord:
    trace_id: str
    request_id: str
    user_id: str
    session_id: str
    role: str
    question: str
    org_id: str = "org_legacy"
    answer_text: str | None = None
    status: str = "running"          # running | succeeded | failed | blocked
    error_code: str | None = None
    blocked: bool = False
    sql_row_count: int | None = None
    rag_doc_count: int | None = None
    has_chart: bool = False
    latency_ms: int | None = None
    evidence_json: str | None = None
    accepted_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        evidence = []
        if self.evidence_json:
            try:
                evidence = json.loads(self.evidence_json)
            except Exception:
                pass
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "org_id": self.org_id,
            "session_id": self.session_id,
            "role": self.role,
            "question": self.question,
            "answer_text": self.answer_text,
            "status": self.status,
            "error_code": self.error_code,
            "blocked": self.blocked,
            "sql_row_count": self.sql_row_count,
            "rag_doc_count": self.rag_doc_count,
            "has_chart": self.has_chart,
            "latency_ms": self.latency_ms,
            "evidence": evidence,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class QueryAuditLog:
    """Postgres-backed audit log for user query activity."""

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    def initialize_schema(self) -> None:
        self._conn.execute(QUERY_AUDIT_TABLE_SQL)
        self._conn.commit()

    def save(self, record: QueryAuditRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO chatbi_query_audit_log (
                trace_id, request_id, user_id, org_id, session_id, role, question,
                answer_text, status, error_code, blocked,
                sql_row_count, rag_doc_count, has_chart,
                latency_ms, evidence_json, accepted_at, finished_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,%s
            )
            ON CONFLICT (trace_id) DO UPDATE SET
                answer_text   = EXCLUDED.answer_text,
                status        = EXCLUDED.status,
                error_code    = EXCLUDED.error_code,
                blocked       = EXCLUDED.blocked,
                sql_row_count = EXCLUDED.sql_row_count,
                rag_doc_count = EXCLUDED.rag_doc_count,
                has_chart     = EXCLUDED.has_chart,
                latency_ms    = EXCLUDED.latency_ms,
                evidence_json = EXCLUDED.evidence_json,
                finished_at   = EXCLUDED.finished_at
            """,
            (
                record.trace_id, record.request_id, record.user_id, record.org_id,
                record.session_id, record.role, record.question,
                record.answer_text, record.status, record.error_code, record.blocked,
                record.sql_row_count, record.rag_doc_count, record.has_chart,
                record.latency_ms, record.evidence_json,
                record.accepted_at, record.finished_at,
            ),
        )
        self._conn.commit()

    def list_recent(
        self,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[QueryAuditRecord, ...]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if org_id:
            where_clauses.append("org_id = %s")
            params.append(org_id)
        if user_id:
            where_clauses.append("user_id ILIKE %s")
            params.append(f"%{user_id}%")
        if status and status != "all":
            where_clauses.append("status = %s")
            params.append(status)
        if from_dt:
            where_clauses.append("accepted_at >= %s")
            params.append(from_dt)
        if to_dt:
            where_clauses.append("accepted_at <= %s")
            params.append(to_dt)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        params.extend([limit, offset])

        cur = self._conn.execute(
            f"""
            SELECT trace_id, request_id, user_id, org_id, session_id, role, question,
                   answer_text, status, error_code, blocked,
                   sql_row_count, rag_doc_count, has_chart,
                   latency_ms, evidence_json, accepted_at, finished_at
            FROM chatbi_query_audit_log
            {where_sql}
            ORDER BY accepted_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()
        return tuple(self._row_to_record(r) for r in rows)

    def count_recent(
        self,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> int:
        where_clauses: list[str] = []
        params: list[Any] = []

        if org_id:
            where_clauses.append("org_id = %s")
            params.append(org_id)
        if user_id:
            where_clauses.append("user_id ILIKE %s")
            params.append(f"%{user_id}%")
        if status and status != "all":
            where_clauses.append("status = %s")
            params.append(status)
        if from_dt:
            where_clauses.append("accepted_at >= %s")
            params.append(from_dt)
        if to_dt:
            where_clauses.append("accepted_at <= %s")
            params.append(to_dt)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        cur = self._conn.execute(
            f"SELECT COUNT(*) FROM chatbi_query_audit_log {where_sql}",
            params,
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def get(self, trace_id: str) -> QueryAuditRecord | None:
        cur = self._conn.execute(
            """
            SELECT trace_id, request_id, user_id, org_id, session_id, role, question,
                   answer_text, status, error_code, blocked,
                   sql_row_count, rag_doc_count, has_chart,
                   latency_ms, evidence_json, accepted_at, finished_at
            FROM chatbi_query_audit_log WHERE trace_id = %s
            """,
            (trace_id,),
        )
        row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def stats(self, org_id: str | None = None) -> dict[str, Any]:
        where = "WHERE org_id = %s" if org_id else ""
        params = [org_id] if org_id else []
        cur = self._conn.execute(
            f"""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'succeeded') as succeeded,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE blocked = TRUE) as blocked,
                ROUND(AVG(latency_ms)) as avg_latency_ms,
                COUNT(DISTINCT user_id) as unique_users
            FROM chatbi_query_audit_log {where}
            """,
            params,
        )
        row = cur.fetchone()
        if not row:
            return {}
        total = int(row[0]) if row[0] else 0
        succeeded = int(row[1]) if row[1] else 0
        return {
            "total": total,
            "succeeded": succeeded,
            "failed": int(row[2]) if row[2] else 0,
            "blocked": int(row[3]) if row[3] else 0,
            "success_rate": round(succeeded / total * 100, 1) if total else 0,
            "avg_latency_ms": int(row[4]) if row[4] else 0,
            "unique_users": int(row[5]) if row[5] else 0,
        }

    @staticmethod
    def _row_to_record(row: Sequence[Any]) -> QueryAuditRecord:
        return QueryAuditRecord(
            trace_id=row[0],
            request_id=row[1],
            user_id=row[2],
            org_id=row[3],
            session_id=row[4],
            role=row[5],
            question=row[6],
            answer_text=row[7],
            status=row[8],
            error_code=row[9],
            blocked=bool(row[10]),
            sql_row_count=row[11],
            rag_doc_count=row[12],
            has_chart=bool(row[13]),
            latency_ms=row[14],
            evidence_json=row[15],
            accepted_at=row[16],
            finished_at=row[17],
        )
