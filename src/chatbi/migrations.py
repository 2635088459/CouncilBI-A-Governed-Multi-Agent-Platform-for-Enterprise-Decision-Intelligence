"""Minimal migration metadata contract for the v2 data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Sequence, cast

from chatbi.core.contracts import utc_now
from chatbi.governance.audit import (
    QUERY_AUDIT_EVENTS_TABLE_SQL,
    SQL_RULE_HITS_TABLE_SQL,
)


V2_SCHEMA_NAMES = (
    "business",
    "semantic",
    "runtime",
    "governance",
    "evaluation",
    "knowledge",
)

V2_SCHEMAS_SQL = "\n".join(
    f"CREATE SCHEMA IF NOT EXISTS {schema_name};" for schema_name in V2_SCHEMA_NAMES
)

MIGRATION_METADATA_TABLE = "schema_migrations"
RUNTIME_SESSIONS_TABLE = "runtime.sessions"
RUNTIME_MESSAGES_TABLE = "runtime.messages"
RUNTIME_QUERY_HISTORY_TABLE = "runtime.query_history"
RUNTIME_QUERY_RESULTS_TABLE = "runtime.query_results"
RUNTIME_AGENT_TRACES_TABLE = "runtime.agent_traces"
GOVERNANCE_QUERY_AUDIT_EVENTS_TABLE = "query_audit_events"
GOVERNANCE_SQL_RULE_HITS_TABLE = "sql_rule_hits"
BUSINESS_REVENUE_BY_MONTH_TABLE = "business.revenue_by_month"
SEMANTIC_VERSIONS_TABLE = "semantic.semantic_versions"
SEMANTIC_METRICS_TABLE = "semantic.metrics"
SEMANTIC_DIMENSIONS_TABLE = "semantic.dimensions"
KNOWLEDGE_DOCUMENTS_TABLE = "knowledge.documents"
KNOWLEDGE_DOC_CHUNKS_TABLE = "knowledge.doc_chunks"
KNOWLEDGE_DOC_EMBEDDINGS_TABLE = "knowledge.doc_embeddings"
GOVERNANCE_ACCESS_POLICIES_TABLE = "governance.access_policies"
EVALUATION_CASES_TABLE = "evaluation.eval_cases"
EVALUATION_RUNS_TABLE = "evaluation.eval_runs"
EVALUATION_SCORES_TABLE = "evaluation.eval_scores"
DEMO_COMPLETED_QUERY_TRACE_ID = "trc_demo_revenue_2026_h1"

MIGRATION_METADATA_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_schema_migrations_applied_at
    ON schema_migrations(applied_at);
"""

RUNTIME_SESSIONS_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS runtime;
CREATE TABLE IF NOT EXISTS runtime.sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_user_created_at
    ON runtime.sessions(user_id, created_at DESC);
"""

RUNTIME_MESSAGES_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS runtime;
CREATE TABLE IF NOT EXISTS runtime.messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES runtime.sessions(session_id),
    trace_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_messages_session_created_at
    ON runtime.messages(session_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_runtime_messages_trace_id
    ON runtime.messages(trace_id);
"""

RUNTIME_QUERY_HISTORY_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS runtime;
CREATE TABLE IF NOT EXISTS runtime.query_history (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES runtime.sessions(session_id),
    message_id TEXT NOT NULL REFERENCES runtime.messages(message_id),
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'degraded')),
    question TEXT NOT NULL,
    sql_text TEXT,
    final_answer JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_query_history_session_created_at
    ON runtime.query_history(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_query_history_status_created_at
    ON runtime.query_history(status, created_at DESC);
"""

RUNTIME_QUERY_RESULTS_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS runtime;
CREATE TABLE IF NOT EXISTS runtime.query_results (
    query_result_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL UNIQUE,
    message_id TEXT NOT NULL REFERENCES runtime.messages(message_id),
    sql_hash TEXT NOT NULL,
    table_result JSONB NOT NULL,
    chart_spec JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_query_results_trace_id
    ON runtime.query_results(trace_id);
CREATE INDEX IF NOT EXISTS idx_runtime_query_results_message_id
    ON runtime.query_results(message_id);
CREATE INDEX IF NOT EXISTS idx_runtime_query_results_sql_hash
    ON runtime.query_results(sql_hash);
"""

RUNTIME_AGENT_TRACES_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS runtime;
CREATE TABLE IF NOT EXISTS runtime.agent_traces (
    agent_trace_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    query_result_id TEXT REFERENCES runtime.query_results(query_result_id),
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'skipped')),
    input_summary TEXT,
    output_summary TEXT,
    latency_ms INTEGER CHECK (latency_ms >= 0),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_agent_traces_trace_id
    ON runtime.agent_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_runtime_agent_traces_query_result_id
    ON runtime.agent_traces(query_result_id);
CREATE INDEX IF NOT EXISTS idx_runtime_agent_traces_agent_status
    ON runtime.agent_traces(agent_name, status);
"""

GOVERNANCE_AUDIT_TABLES_SQL = f"""
CREATE SCHEMA IF NOT EXISTS governance;
{QUERY_AUDIT_EVENTS_TABLE_SQL}
{SQL_RULE_HITS_TABLE_SQL}
"""

READONLY_DATABASE_ROLE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'chatbi_readonly'
    ) THEN
        CREATE ROLE chatbi_readonly LOGIN PASSWORD 'chatbi_readonly_password';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA business TO chatbi_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA business TO chatbi_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA business
    GRANT SELECT ON TABLES TO chatbi_readonly;
ALTER ROLE chatbi_readonly SET search_path = business, public;
"""

BUSINESS_REVENUE_BY_MONTH_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS business;
CREATE TABLE IF NOT EXISTS business.revenue_by_month (
    month TEXT PRIMARY KEY,
    revenue NUMERIC NOT NULL CHECK (revenue >= 0)
);
INSERT INTO business.revenue_by_month (month, revenue)
VALUES
    ('2026-01', 1000.0),
    ('2026-02', 1120.0),
    ('2026-03', 1180.0),
    ('2026-04', 1210.0),
    ('2026-05', 1290.0),
    ('2026-06', 1350.0)
ON CONFLICT (month) DO UPDATE SET
    revenue = EXCLUDED.revenue;
"""

SEMANTIC_CATALOG_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS semantic;
CREATE TABLE IF NOT EXISTS semantic.semantic_versions (
    semantic_version_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic.metrics (
    metric_id TEXT NOT NULL,
    description TEXT NOT NULL,
    table_name TEXT NOT NULL,
    formula TEXT NOT NULL,
    semantic_version_id TEXT NOT NULL REFERENCES semantic.semantic_versions(semantic_version_id),
    synonyms TEXT[] NOT NULL DEFAULT '{}',
    owner TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'deprecated')),
    PRIMARY KEY (metric_id, semantic_version_id)
);
CREATE TABLE IF NOT EXISTS semantic.dimensions (
    dimension_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    expression TEXT NOT NULL,
    grain TEXT,
    semantic_version_id TEXT NOT NULL REFERENCES semantic.semantic_versions(semantic_version_id),
    PRIMARY KEY (dimension_id, semantic_version_id)
);
CREATE INDEX IF NOT EXISTS idx_semantic_metrics_version_status
    ON semantic.metrics(semantic_version_id, status);
CREATE INDEX IF NOT EXISTS idx_semantic_dimensions_version
    ON semantic.dimensions(semantic_version_id);
"""

SEMANTIC_REVENUE_SEED_SQL = """
INSERT INTO semantic.semantic_versions (
    semantic_version_id,
    description,
    created_at
)
VALUES (
    'sem_v1',
    'Initial semantic layer with governed revenue metric.',
    '2026-06-25T00:00:00Z'
)
ON CONFLICT (semantic_version_id) DO UPDATE SET
    description = EXCLUDED.description;

INSERT INTO semantic.metrics (
    metric_id,
    description,
    table_name,
    formula,
    semantic_version_id,
    synonyms,
    owner,
    status
)
VALUES (
    'revenue',
    'Total paid order amount.',
    'orders',
    'SUM(orders.order_amount) WHERE orders.status = ''paid''',
    'sem_v1',
    ARRAY['sales amount', 'paid order amount', 'total sales'],
    'analytics',
    'active'
)
ON CONFLICT (metric_id, semantic_version_id) DO UPDATE SET
    description = EXCLUDED.description,
    table_name = EXCLUDED.table_name,
    formula = EXCLUDED.formula,
    synonyms = EXCLUDED.synonyms,
    owner = EXCLUDED.owner,
    status = EXCLUDED.status;

INSERT INTO semantic.dimensions (
    dimension_id,
    table_name,
    expression,
    grain,
    semantic_version_id
)
VALUES (
    'order_month',
    'orders',
    'DATE_TRUNC(''month'', orders.order_date)::DATE',
    'month',
    'sem_v1'
)
ON CONFLICT (dimension_id, semantic_version_id) DO UPDATE SET
    table_name = EXCLUDED.table_name,
    expression = EXCLUDED.expression,
    grain = EXCLUDED.grain;
"""

KNOWLEDGE_RAG_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE TABLE IF NOT EXISTS knowledge.documents (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    publish_time TIMESTAMPTZ NOT NULL,
    business_tags TEXT[] NOT NULL DEFAULT '{}',
    allowed_roles TEXT[] NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS knowledge.doc_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES knowledge.documents(source_id),
    chunk_index INTEGER NOT NULL CHECK (chunk_index > 0),
    chunk_text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS knowledge.doc_embeddings (
    embedding_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL REFERENCES knowledge.doc_chunks(chunk_id),
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    vector_ref TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_doc_type_publish_time
    ON knowledge.documents(doc_type, publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_business_tags
    ON knowledge.documents USING GIN (business_tags);
CREATE INDEX IF NOT EXISTS idx_knowledge_doc_chunks_source_id
    ON knowledge.doc_chunks(source_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_doc_chunks_source_chunk_index
    ON knowledge.doc_chunks(source_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_knowledge_doc_embeddings_chunk_id
    ON knowledge.doc_embeddings(chunk_id);
"""

KNOWLEDGE_RAG_SEED_SQL = """
INSERT INTO knowledge.documents (
    source_id,
    title,
    doc_type,
    publish_time,
    business_tags,
    allowed_roles
)
VALUES (
    'rag_revenue_policy_2026',
    'Revenue metric policy and anomaly explanation',
    'policy',
    '2026-06-25T00:00:00Z',
    ARRAY['revenue', 'anomaly', 'kpi'],
    ARRAY['analyst', 'admin']
)
ON CONFLICT (source_id) DO UPDATE SET
    title = EXCLUDED.title,
    doc_type = EXCLUDED.doc_type,
    publish_time = EXCLUDED.publish_time,
    business_tags = EXCLUDED.business_tags,
    allowed_roles = EXCLUDED.allowed_roles;

INSERT INTO knowledge.doc_chunks (
    chunk_id,
    source_id,
    chunk_index,
    chunk_text,
    metadata
)
VALUES (
    'rag_revenue_policy_2026_chunk_1',
    'rag_revenue_policy_2026',
    1,
    'Revenue is calculated from paid orders only. A month-over-month spike should be explained with campaign, refund, and region context.',
    '{"fixture": "rag", "metric": "revenue"}'::jsonb
)
ON CONFLICT (chunk_id) DO UPDATE SET
    source_id = EXCLUDED.source_id,
    chunk_index = EXCLUDED.chunk_index,
    chunk_text = EXCLUDED.chunk_text,
    metadata = EXCLUDED.metadata;

INSERT INTO knowledge.doc_embeddings (
    embedding_id,
    chunk_id,
    embedding_model,
    embedding_dimensions,
    vector_ref
)
VALUES (
    'rag_revenue_policy_2026_embedding_1',
    'rag_revenue_policy_2026_chunk_1',
    'local-deterministic-v1',
    8,
    'pgvector://knowledge.doc_chunks/rag_revenue_policy_2026_chunk_1'
)
ON CONFLICT (embedding_id) DO UPDATE SET
    chunk_id = EXCLUDED.chunk_id,
    embedding_model = EXCLUDED.embedding_model,
    embedding_dimensions = EXCLUDED.embedding_dimensions,
    vector_ref = EXCLUDED.vector_ref;
"""

GOVERNANCE_POLICY_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS governance;
CREATE TABLE IF NOT EXISTS governance.access_policies (
    policy_id TEXT PRIMARY KEY,
    object_name TEXT NOT NULL,
    field_name TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('P0', 'P1', 'P2')),
    allowed_roles TEXT[] NOT NULL DEFAULT '{}',
    action TEXT NOT NULL CHECK (action IN ('allow', 'mask', 'deny')),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_governance_access_policies_object_field
    ON governance.access_policies(object_name, field_name);
CREATE INDEX IF NOT EXISTS idx_governance_access_policies_classification_action
    ON governance.access_policies(classification, action);
"""

GOVERNANCE_RESTRICTED_FIELD_POLICY_SEED_SQL = """
INSERT INTO governance.access_policies (
    policy_id,
    object_name,
    field_name,
    classification,
    allowed_roles,
    action,
    reason,
    created_at
)
VALUES (
    'pol_customers_customer_id_p0',
    'customers',
    'customer_id',
    'P0',
    ARRAY['admin'],
    'deny',
    'Customer identifiers are P0 direct identifiers and are denied for normal analytics users.',
    '2026-06-25T00:00:00Z'
)
ON CONFLICT (policy_id) DO UPDATE SET
    object_name = EXCLUDED.object_name,
    field_name = EXCLUDED.field_name,
    classification = EXCLUDED.classification,
    allowed_roles = EXCLUDED.allowed_roles,
    action = EXCLUDED.action,
    reason = EXCLUDED.reason,
    created_at = EXCLUDED.created_at;
"""

EVALUATION_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS evaluation;
CREATE TABLE IF NOT EXISTS evaluation.eval_cases (
    eval_case_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    expected_metric_id TEXT NOT NULL,
    expected_sql_pattern TEXT NOT NULL,
    expected_answer JSONB NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation.eval_runs (
    eval_run_id TEXT PRIMARY KEY,
    eval_suite_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'degraded')),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS evaluation.eval_scores (
    eval_score_id TEXT PRIMARY KEY,
    eval_run_id TEXT NOT NULL REFERENCES evaluation.eval_runs(eval_run_id),
    eval_case_id TEXT NOT NULL REFERENCES evaluation.eval_cases(eval_case_id),
    trace_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    score NUMERIC NOT NULL CHECK (score >= 0 AND score <= 1),
    passed BOOLEAN NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluation_eval_cases_metric_tags
    ON evaluation.eval_cases(expected_metric_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_eval_runs_suite_started_at
    ON evaluation.eval_runs(eval_suite_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_evaluation_eval_scores_run_case
    ON evaluation.eval_scores(eval_run_id, eval_case_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_eval_scores_trace_id
    ON evaluation.eval_scores(trace_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_eval_scores_run_case_metric
    ON evaluation.eval_scores(eval_run_id, eval_case_id, metric_name);
"""

EVALUATION_REVENUE_DEMO_SEED_SQL = """
INSERT INTO evaluation.eval_cases (
    eval_case_id,
    question,
    expected_metric_id,
    expected_sql_pattern,
    expected_answer,
    tags,
    created_at
)
VALUES (
    'case_revenue_kpi_2026_h1',
    'What is revenue by month for the first half of 2026?',
    'revenue',
    'SUM(orders.order_amount)',
    '{"metric": "revenue", "grain": "month"}'::jsonb,
    ARRAY['kpi', 'revenue', 'demo'],
    '2026-06-25T00:00:00Z'
)
ON CONFLICT (eval_case_id) DO UPDATE SET
    question = EXCLUDED.question,
    expected_metric_id = EXCLUDED.expected_metric_id,
    expected_sql_pattern = EXCLUDED.expected_sql_pattern,
    expected_answer = EXCLUDED.expected_answer,
    tags = EXCLUDED.tags,
    created_at = EXCLUDED.created_at;
"""

DEMO_COMPLETED_QUERY_SEED_SQL = """
INSERT INTO runtime.sessions (
    session_id,
    user_id,
    title,
    created_at,
    updated_at
)
VALUES (
    'sess_demo_revenue_2026_h1',
    'demo_analyst',
    'Revenue KPI demo',
    '2026-06-25T00:00:00Z',
    '2026-06-25T00:00:00Z'
)
ON CONFLICT (session_id) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    title = EXCLUDED.title,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at;

INSERT INTO runtime.messages (
    message_id,
    session_id,
    trace_id,
    role,
    content,
    created_at
)
VALUES (
    'msg_demo_revenue_question',
    'sess_demo_revenue_2026_h1',
    'trc_demo_revenue_2026_h1',
    'user',
    'What is revenue by month for the first half of 2026?',
    '2026-06-25T00:00:01Z'
)
ON CONFLICT (message_id) DO UPDATE SET
    session_id = EXCLUDED.session_id,
    trace_id = EXCLUDED.trace_id,
    role = EXCLUDED.role,
    content = EXCLUDED.content,
    created_at = EXCLUDED.created_at;

INSERT INTO runtime.query_history (
    trace_id,
    session_id,
    message_id,
    status,
    question,
    sql_text,
    final_answer,
    created_at
)
VALUES (
    'trc_demo_revenue_2026_h1',
    'sess_demo_revenue_2026_h1',
    'msg_demo_revenue_question',
    'succeeded',
    'What is revenue by month for the first half of 2026?',
    'SELECT month, revenue FROM business.revenue_by_month ORDER BY month',
    '{"answer_text": "Revenue increased from 1000.0 in January to 1350.0 in June.", "confidence": 1.0}'::jsonb,
    '2026-06-25T00:00:01Z'
)
ON CONFLICT (trace_id) DO UPDATE SET
    session_id = EXCLUDED.session_id,
    message_id = EXCLUDED.message_id,
    status = EXCLUDED.status,
    question = EXCLUDED.question,
    sql_text = EXCLUDED.sql_text,
    final_answer = EXCLUDED.final_answer,
    created_at = EXCLUDED.created_at;

INSERT INTO runtime.query_results (
    query_result_id,
    trace_id,
    message_id,
    sql_hash,
    table_result,
    chart_spec,
    created_at
)
VALUES (
    'qr_demo_revenue_2026_h1',
    'trc_demo_revenue_2026_h1',
    'msg_demo_revenue_question',
    'sqlhash_demo_revenue_2026_h1',
    '{"columns": ["month", "revenue"], "rows": [["2026-01", 1000.0], ["2026-02", 1120.0], ["2026-03", 1180.0], ["2026-04", 1210.0], ["2026-05", 1290.0], ["2026-06", 1350.0]]}'::jsonb,
    '{"type": "line", "x": "month", "y": "revenue"}'::jsonb,
    '2026-06-25T00:00:02Z'
)
ON CONFLICT (query_result_id) DO UPDATE SET
    trace_id = EXCLUDED.trace_id,
    message_id = EXCLUDED.message_id,
    sql_hash = EXCLUDED.sql_hash,
    table_result = EXCLUDED.table_result,
    chart_spec = EXCLUDED.chart_spec,
    created_at = EXCLUDED.created_at;

INSERT INTO runtime.agent_traces (
    agent_trace_id,
    trace_id,
    query_result_id,
    agent_name,
    status,
    input_summary,
    output_summary,
    latency_ms,
    created_at
)
VALUES (
    'agt_demo_sql_revenue_2026_h1',
    'trc_demo_revenue_2026_h1',
    'qr_demo_revenue_2026_h1',
    'sql_agent',
    'succeeded',
    'Generated governed revenue SQL for monthly grain.',
    'Returned six monthly revenue rows.',
    42,
    '2026-06-25T00:00:03Z'
)
ON CONFLICT (agent_trace_id) DO UPDATE SET
    trace_id = EXCLUDED.trace_id,
    query_result_id = EXCLUDED.query_result_id,
    agent_name = EXCLUDED.agent_name,
    status = EXCLUDED.status,
    input_summary = EXCLUDED.input_summary,
    output_summary = EXCLUDED.output_summary,
    latency_ms = EXCLUDED.latency_ms,
    created_at = EXCLUDED.created_at;

INSERT INTO query_audit_events (
    audit_event_id,
    trace_id,
    user_id,
    role,
    sql_hash,
    decision,
    latency_ms,
    created_at
)
VALUES (
    'aud_demo_revenue_2026_h1',
    'trc_demo_revenue_2026_h1',
    'demo_analyst',
    'analyst',
    'sqlhash_demo_revenue_2026_h1',
    'allow',
    7,
    '2026-06-25T00:00:04Z'
)
ON CONFLICT (audit_event_id) DO UPDATE SET
    trace_id = EXCLUDED.trace_id,
    user_id = EXCLUDED.user_id,
    role = EXCLUDED.role,
    sql_hash = EXCLUDED.sql_hash,
    decision = EXCLUDED.decision,
    latency_ms = EXCLUDED.latency_ms,
    created_at = EXCLUDED.created_at;

INSERT INTO evaluation.eval_runs (
    eval_run_id,
    eval_suite_id,
    status,
    started_at,
    completed_at,
    summary
)
VALUES (
    'eval_run_demo_revenue_2026_h1',
    'demo_data_model_suite',
    'succeeded',
    '2026-06-25T00:00:05Z',
    '2026-06-25T00:00:06Z',
    '{"total_cases": 1, "passed_cases": 1}'::jsonb
)
ON CONFLICT (eval_run_id) DO UPDATE SET
    eval_suite_id = EXCLUDED.eval_suite_id,
    status = EXCLUDED.status,
    started_at = EXCLUDED.started_at,
    completed_at = EXCLUDED.completed_at,
    summary = EXCLUDED.summary;

INSERT INTO evaluation.eval_scores (
    eval_score_id,
    eval_run_id,
    eval_case_id,
    trace_id,
    metric_name,
    score,
    passed,
    details,
    created_at
)
VALUES (
    'eval_score_demo_revenue_2026_h1',
    'eval_run_demo_revenue_2026_h1',
    'case_revenue_kpi_2026_h1',
    'trc_demo_revenue_2026_h1',
    'sql_correctness',
    1.0,
    TRUE,
    '{"matched_metric": "revenue", "joined_records": ["message", "query_result", "agent_trace", "audit_event", "eval_score"]}'::jsonb,
    '2026-06-25T00:00:07Z'
)
ON CONFLICT (eval_score_id) DO UPDATE SET
    eval_run_id = EXCLUDED.eval_run_id,
    eval_case_id = EXCLUDED.eval_case_id,
    trace_id = EXCLUDED.trace_id,
    metric_name = EXCLUDED.metric_name,
    score = EXCLUDED.score,
    passed = EXCLUDED.passed,
    details = EXCLUDED.details,
    created_at = EXCLUDED.created_at;
"""

DEMO_TRACE_JOIN_SQL = """
SELECT
    history.trace_id,
    message.message_id,
    query_result.query_result_id,
    agent_trace.agent_trace_id,
    audit_event.audit_event_id,
    eval_score.eval_score_id,
    eval_score.score,
    history.status
FROM runtime.query_history AS history
JOIN runtime.messages AS message
    ON message.message_id = history.message_id
JOIN runtime.query_results AS query_result
    ON query_result.trace_id = history.trace_id
JOIN runtime.agent_traces AS agent_trace
    ON agent_trace.trace_id = history.trace_id
JOIN query_audit_events AS audit_event
    ON audit_event.trace_id = history.trace_id
JOIN evaluation.eval_scores AS eval_score
    ON eval_score.trace_id = history.trace_id
WHERE history.trace_id = %s;
"""

BASE_MIGRATION_VERSION = "001_base_runtime_foundation"
BASE_MIGRATION_SQL_STATEMENTS = (
    V2_SCHEMAS_SQL,
    MIGRATION_METADATA_TABLE_SQL,
    BUSINESS_REVENUE_BY_MONTH_TABLE_SQL,
    SEMANTIC_CATALOG_TABLES_SQL,
    SEMANTIC_REVENUE_SEED_SQL,
    KNOWLEDGE_RAG_TABLES_SQL,
    KNOWLEDGE_RAG_SEED_SQL,
    GOVERNANCE_POLICY_TABLES_SQL,
    GOVERNANCE_RESTRICTED_FIELD_POLICY_SEED_SQL,
    EVALUATION_TABLES_SQL,
    EVALUATION_REVENUE_DEMO_SEED_SQL,
    RUNTIME_SESSIONS_TABLE_SQL,
    RUNTIME_MESSAGES_TABLE_SQL,
    RUNTIME_QUERY_HISTORY_TABLE_SQL,
    RUNTIME_QUERY_RESULTS_TABLE_SQL,
    RUNTIME_AGENT_TRACES_TABLE_SQL,
    GOVERNANCE_AUDIT_TABLES_SQL,
    DEMO_COMPLETED_QUERY_SEED_SQL,
)


class MigrationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MigrationResult:
    version: str
    status: MigrationStatus
    applied_at: datetime = field(default_factory=utc_now)
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version is required")
        if self.status is MigrationStatus.SUCCEEDED and self.error is not None:
            raise ValueError("succeeded migration must not include error")
        if self.status is MigrationStatus.FAILED and not (self.error or "").strip():
            raise ValueError("failed migration must include error")


class MigrationMetadataConnection(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        ...

    def fetchone(self) -> Sequence[object] | None:
        ...

    def commit(self) -> None:
        ...


class MigrationMetadataStore:
    """Persist which schema migrations have already run."""

    def __init__(self, connection: MigrationMetadataConnection) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        self._connection.execute(MIGRATION_METADATA_TABLE_SQL)
        self._connection.commit()

    def save_result(self, result: MigrationResult) -> None:
        self._connection.execute(
            """
            INSERT INTO schema_migrations (
                version,
                applied_at,
                status,
                error
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (version) DO UPDATE SET
                applied_at = EXCLUDED.applied_at,
                status = EXCLUDED.status,
                error = EXCLUDED.error
            """,
            (
                result.version,
                result.applied_at,
                result.status.value,
                result.error,
            ),
        )
        self._connection.commit()

    def get_result(self, version: str) -> MigrationResult | None:
        self._connection.execute(
            """
            SELECT version, applied_at, status, error
            FROM schema_migrations
            WHERE version = %s
            """,
            (version,),
        )
        row = self._connection.fetchone()
        if row is None:
            return None

        return MigrationResult(
            version=cast(str, row[0]),
            applied_at=cast(datetime, row[1]),
            status=MigrationStatus(cast(str, row[2])),
            error=cast(str | None, row[3]),
        )


class MigrationRunner:
    """Apply the current base migration in a deterministic order."""

    def __init__(
        self,
        connection: MigrationMetadataConnection,
        metadata_store: MigrationMetadataStore | None = None,
    ) -> None:
        self._connection = connection
        self._metadata_store = metadata_store or MigrationMetadataStore(connection)

    def apply_base_migration(self) -> MigrationResult:
        try:
            for statement in BASE_MIGRATION_SQL_STATEMENTS:
                self._connection.execute(statement)
            result = MigrationResult(
                version=BASE_MIGRATION_VERSION,
                status=MigrationStatus.SUCCEEDED,
            )
        except Exception as exc:
            result = MigrationResult(
                version=BASE_MIGRATION_VERSION,
                status=MigrationStatus.FAILED,
                error=str(exc) or exc.__class__.__name__,
            )
        self._metadata_store.save_result(result)
        return result
