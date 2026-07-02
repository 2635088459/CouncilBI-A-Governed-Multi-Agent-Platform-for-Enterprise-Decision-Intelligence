from chatbi.data_model import (
    DataDomain,
    QualityRuleType,
    SensitivityClass,
    build_default_data_model_catalog,
)


def test_data_model_includes_required_core_business_tables() -> None:
    catalog = build_default_data_model_catalog()

    assert set(catalog.business_table_names()) == {
        "orders",
        "refunds",
        "customers",
        "products",
        "regions",
        "web_events",
        "support_tickets",
        "marketing_campaigns",
    }


def test_data_model_includes_semantic_knowledge_runtime_and_cache_tables() -> None:
    catalog = build_default_data_model_catalog()

    assert set(catalog.table_names_for_domain(DataDomain.SEMANTIC_GOVERNANCE)) == {
        "metrics_catalog",
        "dimension_catalog",
        "semantic_versions",
    }
    assert set(catalog.table_names_for_domain(DataDomain.KNOWLEDGE_RETRIEVAL)) == {
        "documents",
        "doc_chunks",
        "doc_embeddings",
        "rag.documents",
        "rag.chunks",
        "rag.embedding_metadata",
        "rag.index_jobs",
        "rag.evidence_events",
    }
    assert set(catalog.table_names_for_domain(DataDomain.RUNTIME_GOVERNANCE)) == {
        "sessions",
        "messages",
        "query_results",
        "query_history",
        "audit_events",
        "query_audit_events",
        "sql_rule_hits",
        "agent_traces",
        "eval_runs",
    }
    assert set(catalog.table_names_for_domain(DataDomain.ANALYTICS_RESULTS)) == {
        "analytics.results",
    }
    assert set(catalog.table_names_for_domain(DataDomain.CONFIG_CACHE)) == {
        "system_configs",
        "prompt_versions",
        "cache_keys",
    }


def test_runtime_sessions_table_tracks_user_session_lifecycle() -> None:
    catalog = build_default_data_model_catalog()

    sessions = catalog.get_table("sessions")

    assert sessions is not None
    assert sessions.primary_key_columns == ("session_id",)
    assert sessions.get_column("user_id") is not None
    assert sessions.get_column("created_at") is not None
    assert sessions.get_column("updated_at") is not None
    assert ("user_id", "created_at") in sessions.indexes
    assert sessions.retention_days == 180


def test_runtime_messages_table_links_session_trace_and_content() -> None:
    catalog = build_default_data_model_catalog()

    messages = catalog.get_table("messages")
    session_id = catalog.get_column("messages", "session_id")

    assert messages is not None
    assert messages.primary_key_columns == ("message_id",)
    assert session_id is not None
    assert session_id.foreign_key == "sessions.session_id"
    assert messages.get_column("trace_id") is not None
    assert messages.get_column("role") is not None
    assert messages.get_column("content") is not None
    assert ("session_id", "created_at") in messages.indexes
    assert ("trace_id",) in messages.indexes
    assert messages.retention_days == 180


def test_runtime_query_results_table_keeps_one_result_per_trace() -> None:
    catalog = build_default_data_model_catalog()

    query_results = catalog.get_table("query_results")
    message_id = catalog.get_column("query_results", "message_id")

    assert query_results is not None
    assert query_results.primary_key_columns == ("query_result_id",)
    assert message_id is not None
    assert message_id.foreign_key == "messages.message_id"
    assert query_results.get_column("trace_id") is not None
    assert query_results.get_column("sql_hash") is not None
    assert query_results.get_column("table_result") is not None
    assert query_results.get_column("chart_spec") is not None
    assert ("trace_id",) in query_results.indexes
    assert ("trace_id",) in query_results.unique_constraints
    assert ("message_id",) in query_results.indexes
    assert ("sql_hash",) in query_results.indexes
    assert query_results.retention_days == 180


def test_runtime_query_history_table_persists_final_answer_and_lookup_indexes() -> None:
    catalog = build_default_data_model_catalog()

    query_history = catalog.get_table("query_history")
    session_id = catalog.get_column("query_history", "session_id")
    message_id = catalog.get_column("query_history", "message_id")

    assert query_history is not None
    assert query_history.primary_key_columns == ("trace_id",)
    assert session_id is not None
    assert session_id.foreign_key == "sessions.session_id"
    assert message_id is not None
    assert message_id.foreign_key == "messages.message_id"
    assert query_history.get_column("status") is not None
    assert query_history.get_column("question") is not None
    assert query_history.get_column("sql_text") is not None
    assert query_history.get_column("final_answer") is not None
    assert query_history.get_column("created_at") is not None
    assert ("session_id", "created_at") in query_history.indexes
    assert ("status", "created_at") in query_history.indexes
    assert query_history.retention_days == 180


def test_runtime_agent_traces_table_links_trace_and_query_result() -> None:
    catalog = build_default_data_model_catalog()

    agent_traces = catalog.get_table("agent_traces")
    trace_id = catalog.get_column("agent_traces", "trace_id")
    query_result_id = catalog.get_column("agent_traces", "query_result_id")

    assert agent_traces is not None
    assert agent_traces.primary_key_columns == ("agent_trace_id",)
    assert trace_id is not None
    assert trace_id.foreign_key == "query_history.trace_id"
    assert query_result_id is not None
    assert query_result_id.foreign_key == "query_results.query_result_id"
    assert agent_traces.get_column("agent_name") is not None
    assert agent_traces.get_column("status") is not None
    assert agent_traces.get_column("latency_ms") is not None
    assert ("trace_id",) in agent_traces.indexes
    assert ("query_result_id",) in agent_traces.indexes
    assert ("agent_name", "status") in agent_traces.indexes


def test_orders_table_has_partition_column_for_date_range_scans() -> None:
    catalog = build_default_data_model_catalog()

    orders = catalog.get_table("orders")

    assert orders is not None
    assert orders.partition_column == "order_date"
    assert "orders" in catalog.partitioned_table_names()


def test_core_metric_definitions_are_canonical() -> None:
    catalog = build_default_data_model_catalog()

    revenue = catalog.get_metric("revenue")
    refund_rate = catalog.get_metric("refund_rate")
    active_users = catalog.get_metric("active_users")
    order_count = catalog.get_metric("order_count")

    assert set(catalog.metric_names()) == {
        "revenue",
        "refund_rate",
        "active_users",
        "order_count",
    }
    assert revenue is not None
    assert revenue.sql_definition == "SUM(orders.order_amount) WHERE status='paid'"
    assert revenue.source_tables == ("orders",)
    assert refund_rate is not None
    assert refund_rate.sql_definition == "SUM(refunds.refund_amount) / SUM(orders.order_amount)"
    assert active_users is not None
    assert active_users.sql_definition == "COUNT(DISTINCT web_events.customer_id) per day"
    assert order_count is not None
    assert order_count.sql_definition == "COUNT(DISTINCT orders.order_id)"


def test_knowledge_model_stores_document_chunk_and_embedding_metadata() -> None:
    catalog = build_default_data_model_catalog()

    documents = catalog.get_table("documents")
    doc_chunks = catalog.get_table("doc_chunks")
    doc_embeddings = catalog.get_table("doc_embeddings")

    assert documents is not None
    assert documents.get_column("source_id") is not None
    assert documents.get_column("doc_type") is not None
    assert documents.get_column("publish_time") is not None
    assert doc_chunks is not None
    assert doc_chunks.get_column("source_id") is not None
    assert doc_embeddings is not None
    assert doc_embeddings.get_column("embedding_vector") is not None


def test_rag_v2_data_model_tracks_documents_chunks_jobs_and_evidence_events() -> None:
    catalog = build_default_data_model_catalog()

    documents = catalog.get_table("rag.documents")
    chunks = catalog.get_table("rag.chunks")
    embeddings = catalog.get_table("rag.embedding_metadata")
    index_jobs = catalog.get_table("rag.index_jobs")
    evidence_events = catalog.get_table("rag.evidence_events")

    assert documents is not None
    assert documents.primary_key_columns == ("document_id",)
    assert documents.get_column("permission_tags") is not None
    assert ("business_tags",) in documents.indexes
    assert ("permission_tags",) in documents.indexes
    assert chunks is not None
    assert chunks.primary_key_columns == ("chunk_id",)
    chunk_document_id = chunks.get_column("document_id")
    assert chunk_document_id is not None
    assert chunk_document_id.foreign_key == "rag.documents.document_id"
    assert chunks.get_column("token_count") is not None
    assert ("document_id", "position") in chunks.indexes
    assert embeddings is not None
    assert embeddings.get_column("model_name") is not None
    assert embeddings.get_column("model_version") is not None
    assert index_jobs is not None
    assert index_jobs.get_column("status") is not None
    assert evidence_events is not None
    assert evidence_events.get_column("trace_id") is not None
    assert ("trace_id",) in evidence_events.indexes


def test_runtime_governance_tables_keep_trace_id_linkage() -> None:
    catalog = build_default_data_model_catalog()

    query_history = catalog.get_table("query_history")
    audit_events_trace_id = catalog.get_column("audit_events", "trace_id")
    query_audit_events_trace_id = catalog.get_column("query_audit_events", "trace_id")
    sql_rule_hits_trace_id = catalog.get_column("sql_rule_hits", "trace_id")
    sql_rule_hits_audit_event_id = catalog.get_column("sql_rule_hits", "audit_event_id")
    agent_traces_trace_id = catalog.get_column("agent_traces", "trace_id")

    assert query_history is not None
    assert query_history.primary_key_columns == ("trace_id",)
    assert audit_events_trace_id is not None
    assert audit_events_trace_id.foreign_key == "query_history.trace_id"
    assert query_audit_events_trace_id is not None
    assert query_audit_events_trace_id.foreign_key == "query_history.trace_id"
    assert sql_rule_hits_trace_id is not None
    assert sql_rule_hits_trace_id.foreign_key == "query_history.trace_id"
    assert sql_rule_hits_audit_event_id is not None
    assert sql_rule_hits_audit_event_id.foreign_key == "query_audit_events.audit_event_id"
    assert agent_traces_trace_id is not None
    assert agent_traces_trace_id.foreign_key == "query_history.trace_id"


def test_guardrail_v2_audit_tables_store_hash_decision_rule_hits_and_latency() -> None:
    catalog = build_default_data_model_catalog()

    query_audit_events = catalog.get_table("query_audit_events")
    sql_rule_hits = catalog.get_table("sql_rule_hits")

    assert query_audit_events is not None
    assert query_audit_events.primary_key_columns == ("audit_event_id",)
    assert query_audit_events.get_column("sql_hash") is not None
    assert query_audit_events.get_column("decision") is not None
    assert query_audit_events.get_column("latency_ms") is not None
    assert ("trace_id",) in query_audit_events.indexes
    assert ("sql_hash",) in query_audit_events.indexes
    assert sql_rule_hits is not None
    assert sql_rule_hits.primary_key_columns == ("rule_hit_id",)
    assert sql_rule_hits.get_column("rule_code") is not None
    assert sql_rule_hits.get_column("object_name") is not None
    assert sql_rule_hits.get_column("message") is not None
    assert ("audit_event_id",) in sql_rule_hits.indexes
    assert ("rule_code",) in sql_rule_hits.indexes


def test_analytics_v2_results_table_persists_method_parameters_and_forecasts() -> None:
    catalog = build_default_data_model_catalog()

    results = catalog.get_table("analytics.results")

    assert results is not None
    assert results.domain is DataDomain.ANALYTICS_RESULTS
    assert results.primary_key_columns == ("trace_id",)
    assert results.get_column("org_id") is not None
    assert results.get_column("user_id") is not None
    assert results.get_column("metric_id") is not None
    assert results.get_column("semantic_version_id") is not None
    assert results.get_column("parameters") is not None
    assert results.get_column("anomaly_points") is not None
    assert results.get_column("forecast_points") is not None
    assert results.get_column("confidence_interval") is not None
    assert results.get_column("quality_warnings") is not None
    assert results.get_column("method") is not None
    assert results.get_column("model_version") is not None
    assert ("metric_id",) in results.indexes
    assert ("semantic_version_id",) in results.indexes
    assert ("org_id", "trace_id") in results.indexes
    assert ("org_id", "user_id", "trace_id") in results.indexes
    assert results.retention_days == 180


def test_hot_audit_and_history_data_retention_is_at_least_180_days() -> None:
    catalog = build_default_data_model_catalog()

    query_history = catalog.get_table("query_history")
    audit_events = catalog.get_table("audit_events")
    query_audit_events = catalog.get_table("query_audit_events")
    sql_rule_hits = catalog.get_table("sql_rule_hits")

    assert query_history is not None
    assert query_history.retention_days == 180
    assert audit_events is not None
    assert audit_events.retention_days == 180
    assert query_audit_events is not None
    assert query_audit_events.retention_days == 180
    assert sql_rule_hits is not None
    assert sql_rule_hits.retention_days == 180


def test_quality_rules_cover_primary_keys_amounts_and_partitions() -> None:
    catalog = build_default_data_model_catalog()

    orders_rules = catalog.quality_rules_for_table("orders")

    assert any(
        rule.rule_type is QualityRuleType.NON_NULL and rule.column_name == "order_id"
        for rule in orders_rules
    )
    assert any(
        rule.rule_type is QualityRuleType.NON_NEGATIVE and rule.column_name == "order_amount"
        for rule in orders_rules
    )
    assert any(
        rule.rule_type is QualityRuleType.PARTITION_REQUIRED and rule.column_name == "order_date"
        for rule in orders_rules
    )


def test_sensitive_fields_carry_p0_and_p1_classification_tags() -> None:
    catalog = build_default_data_model_catalog()

    customer_id = catalog.get_column("customers", "customer_id")
    user_email = catalog.get_column("customers", "user_email")
    phone = catalog.get_column("customers", "phone")

    assert customer_id is not None
    assert customer_id.sensitivity is SensitivityClass.P0
    assert customer_id.is_p0
    assert user_email is not None
    assert user_email.sensitivity is SensitivityClass.P1
    assert user_email.is_p1
    assert phone is not None
    assert phone.sensitivity is SensitivityClass.P1


def test_catalog_lists_p0_and_p1_fields_for_governance_policies() -> None:
    catalog = build_default_data_model_catalog()

    assert "customers.customer_id" in catalog.p0_fields()
    assert "orders.customer_id" in catalog.p0_fields()
    assert "customers.user_email" in catalog.p1_fields()
    assert "customers.phone" in catalog.p1_fields()
    assert "customers.customer_name" in catalog.p1_fields()
