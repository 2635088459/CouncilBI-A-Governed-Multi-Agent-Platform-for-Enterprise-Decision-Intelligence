from datetime import datetime, timezone
from typing import Sequence

import pytest

from chatbi.migrations import (
    ANALYTICS_V2_RESULTS_TABLE,
    ANALYTICS_V2_TABLES_SQL,
    BASE_MIGRATION_SQL_STATEMENTS,
    BASE_MIGRATION_VERSION,
    BUSINESS_REVENUE_BY_MONTH_TABLE,
    BUSINESS_REVENUE_BY_MONTH_TABLE_SQL,
    DEMO_COMPLETED_QUERY_SEED_SQL,
    DEMO_COMPLETED_QUERY_TRACE_ID,
    DEMO_TRACE_JOIN_SQL,
    EVALUATION_CASES_TABLE,
    EVALUATION_REVENUE_DEMO_SEED_SQL,
    EVALUATION_RUNS_TABLE,
    EVALUATION_SCORES_TABLE,
    EVALUATION_TABLES_SQL,
    GOVERNANCE_AUDIT_TABLES_SQL,
    GOVERNANCE_ACCESS_POLICIES_TABLE,
    GOVERNANCE_POLICY_TABLES_SQL,
    GOVERNANCE_QUERY_AUDIT_EVENTS_TABLE,
    GOVERNANCE_RESTRICTED_FIELD_POLICY_SEED_SQL,
    GOVERNANCE_SQL_RULE_HITS_TABLE,
    KNOWLEDGE_DOC_CHUNKS_TABLE,
    KNOWLEDGE_DOC_EMBEDDINGS_TABLE,
    KNOWLEDGE_DOCUMENTS_TABLE,
    KNOWLEDGE_RAG_SEED_SQL,
    KNOWLEDGE_RAG_TABLES_SQL,
    MIGRATION_METADATA_TABLE,
    MIGRATION_METADATA_TABLE_SQL,
    RAG_V2_CHUNKS_TABLE,
    RAG_V2_DOCUMENTS_TABLE,
    RAG_V2_EMBEDDING_METADATA_TABLE,
    RAG_V2_EVIDENCE_EVENTS_TABLE,
    RAG_V2_INDEX_JOBS_TABLE,
    RAG_V2_TABLES_SQL,
    READONLY_DATABASE_ROLE_SQL,
    RUNTIME_AGENT_TRACES_TABLE,
    RUNTIME_AGENT_TRACES_TABLE_SQL,
    RUNTIME_MESSAGES_TABLE,
    RUNTIME_MESSAGES_TABLE_SQL,
    RUNTIME_QUERY_HISTORY_TABLE,
    RUNTIME_QUERY_HISTORY_TABLE_SQL,
    RUNTIME_QUERY_RESULTS_TABLE,
    RUNTIME_QUERY_RESULTS_TABLE_SQL,
    RUNTIME_SESSIONS_TABLE,
    RUNTIME_SESSIONS_TABLE_SQL,
    SEMANTIC_CATALOG_TABLES_SQL,
    SEMANTIC_DIMENSIONS_TABLE,
    SEMANTIC_METRICS_TABLE,
    SEMANTIC_REVENUE_SEED_SQL,
    SEMANTIC_VERSIONS_TABLE,
    V2_SCHEMA_NAMES,
    V2_SCHEMAS_SQL,
    MigrationMetadataConnection,
    MigrationMetadataStore,
    MigrationResult,
    MigrationRunner,
    MigrationStatus,
)


class FakeMigrationConnection:
    def __init__(self, fail_on_sql: str | None = None) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.next_row: Sequence[object] | None = None
        self.fail_on_sql = fail_on_sql

    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        self.commands.append((sql, tuple(params)))
        if self.fail_on_sql is not None and self.fail_on_sql in sql:
            raise RuntimeError("migration statement failed")
        return object()

    def fetchone(self) -> Sequence[object] | None:
        return self.next_row

    def commit(self) -> None:
        self.commits += 1


def test_v2_schemas_sql_creates_all_required_schema_layers() -> None:
    assert V2_SCHEMA_NAMES == (
        "business",
        "semantic",
        "runtime",
        "governance",
        "evaluation",
        "knowledge",
        "rag",
        "analytics",
    )
    for schema_name in V2_SCHEMA_NAMES:
        assert f"CREATE SCHEMA IF NOT EXISTS {schema_name};" in V2_SCHEMAS_SQL


def test_base_migration_sql_statements_are_ordered_for_dependencies() -> None:
    assert BASE_MIGRATION_VERSION == "001_base_runtime_foundation"
    assert BASE_MIGRATION_SQL_STATEMENTS == (
        V2_SCHEMAS_SQL,
        MIGRATION_METADATA_TABLE_SQL,
        BUSINESS_REVENUE_BY_MONTH_TABLE_SQL,
        SEMANTIC_CATALOG_TABLES_SQL,
        SEMANTIC_REVENUE_SEED_SQL,
        KNOWLEDGE_RAG_TABLES_SQL,
        KNOWLEDGE_RAG_SEED_SQL,
        RAG_V2_TABLES_SQL,
        ANALYTICS_V2_TABLES_SQL,
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


def test_business_revenue_by_month_table_sql_creates_seeded_read_model() -> None:
    normalized_sql = " ".join(BUSINESS_REVENUE_BY_MONTH_TABLE_SQL.split())

    assert BUSINESS_REVENUE_BY_MONTH_TABLE == "business.revenue_by_month"
    assert "CREATE SCHEMA IF NOT EXISTS business" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS business.revenue_by_month" in normalized_sql
    assert "month TEXT PRIMARY KEY" in normalized_sql
    assert "revenue NUMERIC NOT NULL CHECK" in normalized_sql
    assert "INSERT INTO business.revenue_by_month" in normalized_sql
    assert "'2026-01', 1000.0" in normalized_sql
    assert "'2026-06', 1350.0" in normalized_sql
    assert "ON CONFLICT (month) DO UPDATE SET" in normalized_sql


def test_semantic_catalog_tables_sql_creates_metrics_dimensions_and_versions() -> None:
    normalized_sql = " ".join(SEMANTIC_CATALOG_TABLES_SQL.split())

    assert SEMANTIC_VERSIONS_TABLE == "semantic.semantic_versions"
    assert SEMANTIC_METRICS_TABLE == "semantic.metrics"
    assert SEMANTIC_DIMENSIONS_TABLE == "semantic.dimensions"
    assert "CREATE TABLE IF NOT EXISTS semantic.semantic_versions" in normalized_sql
    assert "semantic_version_id TEXT PRIMARY KEY" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS semantic.metrics" in normalized_sql
    assert "metric_id TEXT NOT NULL" in normalized_sql
    assert "formula TEXT NOT NULL" in normalized_sql
    assert "owner TEXT NOT NULL" in normalized_sql
    assert "status TEXT NOT NULL CHECK" in normalized_sql
    assert "'active', 'deprecated'" in normalized_sql
    assert "PRIMARY KEY (metric_id, semantic_version_id)" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS semantic.dimensions" in normalized_sql
    assert "idx_semantic_metrics_version_status" in normalized_sql


def test_semantic_revenue_seed_sql_reproduces_required_metric() -> None:
    normalized_sql = " ".join(SEMANTIC_REVENUE_SEED_SQL.split())

    assert "INSERT INTO semantic.semantic_versions" in normalized_sql
    assert "'sem_v1'" in normalized_sql
    assert "INSERT INTO semantic.metrics" in normalized_sql
    assert "'revenue'" in normalized_sql
    assert "'SUM(orders.order_amount) WHERE orders.status = ''paid'''" in normalized_sql
    assert "ARRAY['sales amount', 'paid order amount', 'total sales']" in normalized_sql
    assert "'analytics'" in normalized_sql
    assert "'active'" in normalized_sql
    assert "INSERT INTO semantic.dimensions" in normalized_sql
    assert "'order_month'" in normalized_sql


def test_knowledge_rag_tables_sql_creates_documents_chunks_and_embedding_metadata() -> None:
    normalized_sql = " ".join(KNOWLEDGE_RAG_TABLES_SQL.split())

    assert KNOWLEDGE_DOCUMENTS_TABLE == "knowledge.documents"
    assert KNOWLEDGE_DOC_CHUNKS_TABLE == "knowledge.doc_chunks"
    assert KNOWLEDGE_DOC_EMBEDDINGS_TABLE == "knowledge.doc_embeddings"
    assert "CREATE SCHEMA IF NOT EXISTS knowledge" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS knowledge.documents" in normalized_sql
    assert "source_id TEXT PRIMARY KEY" in normalized_sql
    assert "doc_type TEXT NOT NULL" in normalized_sql
    assert "publish_time TIMESTAMPTZ NOT NULL" in normalized_sql
    assert "business_tags TEXT[] NOT NULL DEFAULT '{}'" in normalized_sql
    assert "allowed_roles TEXT[] NOT NULL DEFAULT '{}'" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS knowledge.doc_chunks" in normalized_sql
    assert "source_id TEXT NOT NULL REFERENCES knowledge.documents(source_id)" in normalized_sql
    assert "chunk_index INTEGER NOT NULL CHECK" in normalized_sql
    assert "metadata JSONB NOT NULL DEFAULT '{}'::jsonb" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS knowledge.doc_embeddings" in normalized_sql
    assert "chunk_id TEXT NOT NULL REFERENCES knowledge.doc_chunks(chunk_id)" in normalized_sql
    assert "embedding_model TEXT NOT NULL" in normalized_sql
    assert "embedding_dimensions INTEGER NOT NULL CHECK" in normalized_sql
    assert "vector_ref TEXT NOT NULL" in normalized_sql
    assert "idx_knowledge_documents_doc_type_publish_time" in normalized_sql
    assert "idx_knowledge_documents_business_tags" in normalized_sql
    assert "idx_knowledge_doc_chunks_source_id" in normalized_sql
    assert "idx_knowledge_doc_chunks_source_chunk_index" in normalized_sql


def test_knowledge_rag_seed_sql_reproduces_required_rag_fixture() -> None:
    normalized_sql = " ".join(KNOWLEDGE_RAG_SEED_SQL.split())

    assert "INSERT INTO knowledge.documents" in normalized_sql
    assert "'rag_revenue_policy_2026'" in normalized_sql
    assert "'Revenue metric policy and anomaly explanation'" in normalized_sql
    assert "'policy'" in normalized_sql
    assert "ARRAY['revenue', 'anomaly', 'kpi']" in normalized_sql
    assert "ARRAY['analyst', 'admin']" in normalized_sql
    assert "INSERT INTO knowledge.doc_chunks" in normalized_sql
    assert "'rag_revenue_policy_2026_chunk_1'" in normalized_sql
    assert "'{\"fixture\": \"rag\", \"metric\": \"revenue\"}'::jsonb" in normalized_sql
    assert "INSERT INTO knowledge.doc_embeddings" in normalized_sql
    assert "'local-deterministic-v1'" in normalized_sql
    assert "'pgvector://knowledge.doc_chunks/rag_revenue_policy_2026_chunk_1'" in normalized_sql
    assert "ON CONFLICT (embedding_id) DO UPDATE SET" in normalized_sql


def test_rag_v2_tables_sql_creates_spec_v2_rag_tables() -> None:
    normalized_sql = " ".join(RAG_V2_TABLES_SQL.split())

    assert RAG_V2_DOCUMENTS_TABLE == "rag.documents"
    assert RAG_V2_CHUNKS_TABLE == "rag.chunks"
    assert RAG_V2_EMBEDDING_METADATA_TABLE == "rag.embedding_metadata"
    assert RAG_V2_INDEX_JOBS_TABLE == "rag.index_jobs"
    assert RAG_V2_EVIDENCE_EVENTS_TABLE == "rag.evidence_events"
    assert "CREATE SCHEMA IF NOT EXISTS rag" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS rag.documents" in normalized_sql
    assert "document_id TEXT PRIMARY KEY" in normalized_sql
    assert "permission_tags TEXT[] NOT NULL DEFAULT '{}'" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS rag.chunks" in normalized_sql
    assert "document_id TEXT NOT NULL REFERENCES rag.documents(document_id)" in normalized_sql
    assert "token_count INTEGER NOT NULL CHECK" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS rag.embedding_metadata" in normalized_sql
    assert "model_name TEXT NOT NULL" in normalized_sql
    assert "model_version TEXT NOT NULL" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS rag.index_jobs" in normalized_sql
    assert "status TEXT NOT NULL CHECK" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS rag.evidence_events" in normalized_sql
    assert "trace_id TEXT NOT NULL" in normalized_sql
    assert "idx_rag_evidence_events_trace_id" in normalized_sql


def test_analytics_v2_tables_sql_creates_spec_v2_result_table() -> None:
    normalized_sql = " ".join(ANALYTICS_V2_TABLES_SQL.split())

    assert ANALYTICS_V2_RESULTS_TABLE == "analytics.results"
    assert "CREATE SCHEMA IF NOT EXISTS analytics" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS analytics.results" in normalized_sql
    assert "trace_id TEXT PRIMARY KEY" in normalized_sql
    assert "parameters JSONB NOT NULL" in normalized_sql
    assert "anomaly_points JSONB NOT NULL" in normalized_sql
    assert "forecast_points JSONB NOT NULL" in normalized_sql
    assert "quality_warnings TEXT[] NOT NULL DEFAULT '{}'" in normalized_sql
    assert "model_version TEXT NOT NULL" in normalized_sql
    assert "idx_analytics_results_metric_id" in normalized_sql


def test_governance_policy_tables_sql_creates_restricted_field_policy_table() -> None:
    normalized_sql = " ".join(GOVERNANCE_POLICY_TABLES_SQL.split())

    assert GOVERNANCE_ACCESS_POLICIES_TABLE == "governance.access_policies"
    assert "CREATE SCHEMA IF NOT EXISTS governance" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS governance.access_policies" in normalized_sql
    assert "policy_id TEXT PRIMARY KEY" in normalized_sql
    assert "object_name TEXT NOT NULL" in normalized_sql
    assert "field_name TEXT NOT NULL" in normalized_sql
    assert "classification TEXT NOT NULL CHECK" in normalized_sql
    assert "'P0', 'P1', 'P2'" in normalized_sql
    assert "allowed_roles TEXT[] NOT NULL DEFAULT '{}'" in normalized_sql
    assert "action TEXT NOT NULL CHECK" in normalized_sql
    assert "'allow', 'mask', 'deny'" in normalized_sql
    assert "idx_governance_access_policies_object_field" in normalized_sql
    assert "idx_governance_access_policies_classification_action" in normalized_sql


def test_governance_restricted_field_seed_sql_reproduces_permission_fixture() -> None:
    normalized_sql = " ".join(GOVERNANCE_RESTRICTED_FIELD_POLICY_SEED_SQL.split())

    assert "INSERT INTO governance.access_policies" in normalized_sql
    assert "'pol_customers_customer_id_p0'" in normalized_sql
    assert "'customers'" in normalized_sql
    assert "'customer_id'" in normalized_sql
    assert "'P0'" in normalized_sql
    assert "ARRAY['admin']" in normalized_sql
    assert "'deny'" in normalized_sql
    assert "Customer identifiers are P0 direct identifiers" in normalized_sql
    assert "ON CONFLICT (policy_id) DO UPDATE SET" in normalized_sql


def test_evaluation_tables_sql_creates_cases_runs_and_trace_linked_scores() -> None:
    normalized_sql = " ".join(EVALUATION_TABLES_SQL.split())

    assert EVALUATION_CASES_TABLE == "evaluation.eval_cases"
    assert EVALUATION_RUNS_TABLE == "evaluation.eval_runs"
    assert EVALUATION_SCORES_TABLE == "evaluation.eval_scores"
    assert "CREATE SCHEMA IF NOT EXISTS evaluation" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS evaluation.eval_cases" in normalized_sql
    assert "eval_case_id TEXT PRIMARY KEY" in normalized_sql
    assert "question TEXT NOT NULL" in normalized_sql
    assert "expected_metric_id TEXT NOT NULL" in normalized_sql
    assert "expected_sql_pattern TEXT NOT NULL" in normalized_sql
    assert "expected_answer JSONB NOT NULL" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS evaluation.eval_runs" in normalized_sql
    assert "eval_run_id TEXT PRIMARY KEY" in normalized_sql
    assert "eval_suite_id TEXT NOT NULL" in normalized_sql
    assert "status TEXT NOT NULL CHECK" in normalized_sql
    assert "'succeeded', 'failed', 'degraded'" in normalized_sql
    assert "summary JSONB NOT NULL DEFAULT '{}'::jsonb" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS evaluation.eval_scores" in normalized_sql
    assert "eval_run_id TEXT NOT NULL REFERENCES evaluation.eval_runs(eval_run_id)" in normalized_sql
    assert "eval_case_id TEXT NOT NULL REFERENCES evaluation.eval_cases(eval_case_id)" in normalized_sql
    assert "trace_id TEXT NOT NULL" in normalized_sql
    assert "score NUMERIC NOT NULL CHECK (score >= 0 AND score <= 1)" in normalized_sql
    assert "passed BOOLEAN NOT NULL" in normalized_sql
    assert "idx_evaluation_eval_runs_suite_started_at" in normalized_sql
    assert "idx_evaluation_eval_scores_trace_id" in normalized_sql
    assert "idx_evaluation_eval_scores_run_case_metric" in normalized_sql


def test_evaluation_revenue_demo_seed_sql_reproduces_kpi_eval_fixture() -> None:
    normalized_sql = " ".join(EVALUATION_REVENUE_DEMO_SEED_SQL.split())

    assert "INSERT INTO evaluation.eval_cases" in normalized_sql
    assert "'case_revenue_kpi_2026_h1'" in normalized_sql
    assert "'What is revenue by month for the first half of 2026?'" in normalized_sql
    assert "'revenue'" in normalized_sql
    assert "'SUM(orders.order_amount)'" in normalized_sql
    assert "'{\"metric\": \"revenue\", \"grain\": \"month\"}'::jsonb" in normalized_sql
    assert "ARRAY['kpi', 'revenue', 'demo']" in normalized_sql
    assert "ON CONFLICT (eval_case_id) DO UPDATE SET" in normalized_sql


def test_migration_metadata_table_sql_tracks_version_status_and_error() -> None:
    normalized_sql = " ".join(MIGRATION_METADATA_TABLE_SQL.split())

    assert MIGRATION_METADATA_TABLE == "schema_migrations"
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in normalized_sql
    assert "version TEXT PRIMARY KEY" in normalized_sql
    assert "applied_at TIMESTAMPTZ NOT NULL" in normalized_sql
    assert "status TEXT NOT NULL CHECK" in normalized_sql
    assert "'succeeded', 'failed'" in normalized_sql
    assert "error TEXT" in normalized_sql
    assert "idx_schema_migrations_applied_at" in normalized_sql


def test_runtime_sessions_table_sql_creates_schema_table_and_lookup_index() -> None:
    normalized_sql = " ".join(RUNTIME_SESSIONS_TABLE_SQL.split())

    assert RUNTIME_SESSIONS_TABLE == "runtime.sessions"
    assert "CREATE SCHEMA IF NOT EXISTS runtime" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS runtime.sessions" in normalized_sql
    assert "session_id TEXT PRIMARY KEY" in normalized_sql
    assert "user_id TEXT NOT NULL" in normalized_sql
    assert "created_at TIMESTAMPTZ NOT NULL" in normalized_sql
    assert "updated_at TIMESTAMPTZ NOT NULL" in normalized_sql
    assert "idx_runtime_sessions_user_created_at" in normalized_sql
    assert "ON runtime.sessions(user_id, created_at DESC)" in normalized_sql


def test_runtime_messages_table_sql_links_sessions_trace_and_history_index() -> None:
    normalized_sql = " ".join(RUNTIME_MESSAGES_TABLE_SQL.split())

    assert RUNTIME_MESSAGES_TABLE == "runtime.messages"
    assert "CREATE TABLE IF NOT EXISTS runtime.messages" in normalized_sql
    assert "message_id TEXT PRIMARY KEY" in normalized_sql
    assert "session_id TEXT NOT NULL REFERENCES runtime.sessions(session_id)" in normalized_sql
    assert "trace_id TEXT NOT NULL" in normalized_sql
    assert "role TEXT NOT NULL CHECK" in normalized_sql
    assert "'user', 'assistant', 'system'" in normalized_sql
    assert "content TEXT NOT NULL" in normalized_sql
    assert "idx_runtime_messages_session_created_at" in normalized_sql
    assert "ON runtime.messages(session_id, created_at ASC)" in normalized_sql
    assert "idx_runtime_messages_trace_id" in normalized_sql


def test_runtime_query_history_table_sql_persists_final_answer_and_history_lookup_index() -> None:
    normalized_sql = " ".join(RUNTIME_QUERY_HISTORY_TABLE_SQL.split())

    assert RUNTIME_QUERY_HISTORY_TABLE == "runtime.query_history"
    assert "CREATE TABLE IF NOT EXISTS runtime.query_history" in normalized_sql
    assert "trace_id TEXT PRIMARY KEY" in normalized_sql
    assert "session_id TEXT NOT NULL REFERENCES runtime.sessions(session_id)" in normalized_sql
    assert "message_id TEXT NOT NULL REFERENCES runtime.messages(message_id)" in normalized_sql
    assert "status TEXT NOT NULL CHECK" in normalized_sql
    assert "'succeeded', 'failed', 'degraded'" in normalized_sql
    assert "question TEXT NOT NULL" in normalized_sql
    assert "sql_text TEXT" in normalized_sql
    assert "final_answer JSONB" in normalized_sql
    assert "created_at TIMESTAMPTZ NOT NULL" in normalized_sql
    assert "idx_runtime_query_history_session_created_at" in normalized_sql
    assert "ON runtime.query_history(session_id, created_at DESC)" in normalized_sql
    assert "idx_runtime_query_history_status_created_at" in normalized_sql


def test_runtime_query_results_table_sql_enforces_unique_trace_id() -> None:
    normalized_sql = " ".join(RUNTIME_QUERY_RESULTS_TABLE_SQL.split())

    assert RUNTIME_QUERY_RESULTS_TABLE == "runtime.query_results"
    assert "CREATE TABLE IF NOT EXISTS runtime.query_results" in normalized_sql
    assert "query_result_id TEXT PRIMARY KEY" in normalized_sql
    assert "trace_id TEXT NOT NULL UNIQUE" in normalized_sql
    assert "message_id TEXT NOT NULL REFERENCES runtime.messages(message_id)" in normalized_sql
    assert "sql_hash TEXT NOT NULL" in normalized_sql
    assert "table_result JSONB NOT NULL" in normalized_sql
    assert "chart_spec JSONB" in normalized_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_query_results_trace_id" in normalized_sql
    assert "ON runtime.query_results(trace_id)" in normalized_sql
    assert "idx_runtime_query_results_message_id" in normalized_sql


def test_runtime_agent_traces_table_sql_links_trace_and_query_result() -> None:
    normalized_sql = " ".join(RUNTIME_AGENT_TRACES_TABLE_SQL.split())

    assert RUNTIME_AGENT_TRACES_TABLE == "runtime.agent_traces"
    assert "CREATE TABLE IF NOT EXISTS runtime.agent_traces" in normalized_sql
    assert "agent_trace_id TEXT PRIMARY KEY" in normalized_sql
    assert "trace_id TEXT NOT NULL" in normalized_sql
    assert "query_result_id TEXT REFERENCES runtime.query_results(query_result_id)" in normalized_sql
    assert "agent_name TEXT NOT NULL" in normalized_sql
    assert "status TEXT NOT NULL CHECK" in normalized_sql
    assert "'succeeded', 'failed', 'skipped'" in normalized_sql
    assert "latency_ms INTEGER CHECK (latency_ms >= 0)" in normalized_sql
    assert "idx_runtime_agent_traces_trace_id" in normalized_sql
    assert "idx_runtime_agent_traces_query_result_id" in normalized_sql
    assert "idx_runtime_agent_traces_agent_status" in normalized_sql


def test_governance_audit_tables_sql_creates_guardrail_audit_tables() -> None:
    normalized_sql = " ".join(GOVERNANCE_AUDIT_TABLES_SQL.split())

    assert GOVERNANCE_QUERY_AUDIT_EVENTS_TABLE == "query_audit_events"
    assert GOVERNANCE_SQL_RULE_HITS_TABLE == "sql_rule_hits"
    assert "CREATE SCHEMA IF NOT EXISTS governance" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS query_audit_events" in normalized_sql
    assert "trace_id TEXT NOT NULL" in normalized_sql
    assert "sql_hash TEXT NOT NULL" in normalized_sql
    assert "decision TEXT NOT NULL CHECK" in normalized_sql
    assert "'allow', 'deny'" in normalized_sql
    assert "latency_ms INTEGER NOT NULL CHECK" in normalized_sql
    assert "CREATE TABLE IF NOT EXISTS sql_rule_hits" in normalized_sql
    assert "audit_event_id TEXT NOT NULL REFERENCES query_audit_events(audit_event_id)" in normalized_sql
    assert "rule_code TEXT NOT NULL" in normalized_sql
    assert "idx_sql_rule_hits_rule_code" in normalized_sql


def test_demo_completed_query_seed_links_runtime_audit_and_evaluation_by_trace_id() -> None:
    normalized_sql = " ".join(DEMO_COMPLETED_QUERY_SEED_SQL.split())

    assert DEMO_COMPLETED_QUERY_TRACE_ID == "trc_demo_revenue_2026_h1"
    assert normalized_sql.count("'trc_demo_revenue_2026_h1'") >= 5
    assert "INSERT INTO runtime.sessions" in normalized_sql
    assert "'sess_demo_revenue_2026_h1'" in normalized_sql
    assert "'demo_analyst'" in normalized_sql
    assert "INSERT INTO runtime.messages" in normalized_sql
    assert "'msg_demo_revenue_question'" in normalized_sql
    assert "'What is revenue by month for the first half of 2026?'" in normalized_sql
    assert "INSERT INTO runtime.query_history" in normalized_sql
    assert "'succeeded'" in normalized_sql
    assert "'SELECT month, revenue FROM business.revenue_by_month ORDER BY month'" in normalized_sql
    assert "final_answer" in normalized_sql
    assert "INSERT INTO runtime.query_results" in normalized_sql
    assert "'qr_demo_revenue_2026_h1'" in normalized_sql
    assert "'sqlhash_demo_revenue_2026_h1'" in normalized_sql
    assert "'{\"type\": \"line\", \"x\": \"month\", \"y\": \"revenue\"}'::jsonb" in normalized_sql
    assert "INSERT INTO runtime.agent_traces" in normalized_sql
    assert "'agt_demo_sql_revenue_2026_h1'" in normalized_sql
    assert "'sql_agent'" in normalized_sql
    assert "INSERT INTO query_audit_events" in normalized_sql
    assert "'aud_demo_revenue_2026_h1'" in normalized_sql
    assert "'allow'" in normalized_sql
    assert "INSERT INTO evaluation.eval_runs" in normalized_sql
    assert "'eval_run_demo_revenue_2026_h1'" in normalized_sql
    assert "'demo_data_model_suite'" in normalized_sql
    assert "INSERT INTO evaluation.eval_scores" in normalized_sql
    assert "'eval_score_demo_revenue_2026_h1'" in normalized_sql
    assert "'case_revenue_kpi_2026_h1'" in normalized_sql
    assert "'sql_correctness'" in normalized_sql
    assert "1.0" in normalized_sql
    assert "ON CONFLICT (eval_score_id) DO UPDATE SET" in normalized_sql


def test_demo_trace_join_sql_replays_completed_query_records_by_trace_id() -> None:
    normalized_sql = " ".join(DEMO_TRACE_JOIN_SQL.split())

    assert "SELECT history.trace_id" in normalized_sql
    assert "message.message_id" in normalized_sql
    assert "query_result.query_result_id" in normalized_sql
    assert "agent_trace.agent_trace_id" in normalized_sql
    assert "audit_event.audit_event_id" in normalized_sql
    assert "eval_score.eval_score_id" in normalized_sql
    assert "history.status" in normalized_sql
    assert "FROM runtime.query_history AS history" in normalized_sql
    assert "JOIN runtime.messages AS message ON message.message_id = history.message_id" in normalized_sql
    assert "JOIN runtime.query_results AS query_result ON query_result.trace_id = history.trace_id" in normalized_sql
    assert "JOIN runtime.agent_traces AS agent_trace ON agent_trace.trace_id = history.trace_id" in normalized_sql
    assert "JOIN query_audit_events AS audit_event ON audit_event.trace_id = history.trace_id" in normalized_sql
    assert "JOIN evaluation.eval_scores AS eval_score ON eval_score.trace_id = history.trace_id" in normalized_sql
    assert "WHERE history.trace_id = %s" in normalized_sql


def test_readonly_database_role_sql_grants_only_business_select() -> None:
    normalized_sql = " ".join(READONLY_DATABASE_ROLE_SQL.split())

    assert "CREATE ROLE chatbi_readonly LOGIN PASSWORD" in normalized_sql
    assert "GRANT USAGE ON SCHEMA business TO chatbi_readonly" in normalized_sql
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA business TO chatbi_readonly" in normalized_sql
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA business GRANT SELECT ON TABLES TO chatbi_readonly" in normalized_sql
    assert "ALTER ROLE chatbi_readonly SET search_path = business, public" in normalized_sql
    assert "GRANT INSERT" not in normalized_sql
    assert "GRANT UPDATE" not in normalized_sql
    assert "GRANT DELETE" not in normalized_sql


def test_migration_result_accepts_success_without_error() -> None:
    result = MigrationResult(version="001_create_runtime_sessions", status=MigrationStatus.SUCCEEDED)

    assert result.version == "001_create_runtime_sessions"
    assert result.status is MigrationStatus.SUCCEEDED
    assert result.error is None


def test_migration_result_rejects_empty_version() -> None:
    with pytest.raises(ValueError, match="version"):
        MigrationResult(version=" ", status=MigrationStatus.SUCCEEDED)


def test_migration_result_rejects_success_with_error() -> None:
    with pytest.raises(ValueError, match="error"):
        MigrationResult(
            version="001_create_runtime_sessions",
            status=MigrationStatus.SUCCEEDED,
            error="unexpected failure",
        )


def test_migration_result_requires_error_for_failed_status() -> None:
    with pytest.raises(ValueError, match="failed migration"):
        MigrationResult(version="001_create_runtime_sessions", status=MigrationStatus.FAILED)


def test_migration_metadata_store_initializes_schema() -> None:
    connection = FakeMigrationConnection()
    store = MigrationMetadataStore(connection)

    store.initialize_schema()

    assert connection.commands == [(MIGRATION_METADATA_TABLE_SQL, ())]
    assert connection.commits == 1


def test_migration_metadata_store_saves_result_by_version() -> None:
    connection: MigrationMetadataConnection = FakeMigrationConnection()
    store = MigrationMetadataStore(connection)
    applied_at = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)

    store.save_result(
        MigrationResult(
            version="001_create_runtime_sessions",
            status=MigrationStatus.SUCCEEDED,
            applied_at=applied_at,
        )
    )

    fake_connection = connection
    assert isinstance(fake_connection, FakeMigrationConnection)
    sql, params = fake_connection.commands[0]
    assert "INSERT INTO schema_migrations" in sql
    assert "ON CONFLICT (version) DO UPDATE" in sql
    assert params == (
        "001_create_runtime_sessions",
        applied_at,
        "succeeded",
        None,
    )
    assert fake_connection.commits == 1


def test_migration_metadata_store_loads_result_by_version() -> None:
    applied_at = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    connection = FakeMigrationConnection()
    connection.next_row = (
        "001_create_runtime_sessions",
        applied_at,
        "failed",
        "table already exists",
    )
    store = MigrationMetadataStore(connection)

    result = store.get_result("001_create_runtime_sessions")

    assert result is not None
    assert result.version == "001_create_runtime_sessions"
    assert result.applied_at == applied_at
    assert result.status is MigrationStatus.FAILED
    assert result.error == "table already exists"
    assert connection.commands[0][1] == ("001_create_runtime_sessions",)


def test_migration_runner_applies_base_migration_and_records_success() -> None:
    connection = FakeMigrationConnection()
    runner = MigrationRunner(connection)

    result = runner.apply_base_migration()

    executed_sql = tuple(sql for sql, _params in connection.commands[: len(BASE_MIGRATION_SQL_STATEMENTS)])
    audit_sql, audit_params = connection.commands[-1]
    assert result.version == BASE_MIGRATION_VERSION
    assert result.status is MigrationStatus.SUCCEEDED
    assert executed_sql == BASE_MIGRATION_SQL_STATEMENTS
    assert "INSERT INTO schema_migrations" in audit_sql
    assert audit_params[0] == BASE_MIGRATION_VERSION
    assert audit_params[2] == "succeeded"
    assert audit_params[3] is None
    assert connection.commits == 1


def test_migration_runner_records_failure_when_statement_fails() -> None:
    connection = FakeMigrationConnection(fail_on_sql="runtime.messages")
    runner = MigrationRunner(connection)

    result = runner.apply_base_migration()

    audit_sql, audit_params = connection.commands[-1]
    assert result.version == BASE_MIGRATION_VERSION
    assert result.status is MigrationStatus.FAILED
    assert result.error == "migration statement failed"
    assert "INSERT INTO schema_migrations" in audit_sql
    assert audit_params[0] == BASE_MIGRATION_VERSION
    assert audit_params[2] == "failed"
    assert audit_params[3] == "migration statement failed"
