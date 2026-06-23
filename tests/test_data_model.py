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
    }
    assert set(catalog.table_names_for_domain(DataDomain.RUNTIME_GOVERNANCE)) == {
        "query_history",
        "audit_events",
        "agent_traces",
        "eval_runs",
    }
    assert set(catalog.table_names_for_domain(DataDomain.CONFIG_CACHE)) == {
        "system_configs",
        "prompt_versions",
        "cache_keys",
    }


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


def test_runtime_governance_tables_keep_trace_id_linkage() -> None:
    catalog = build_default_data_model_catalog()

    query_history = catalog.get_table("query_history")
    audit_events_trace_id = catalog.get_column("audit_events", "trace_id")
    agent_traces_trace_id = catalog.get_column("agent_traces", "trace_id")

    assert query_history is not None
    assert query_history.primary_key_columns == ("trace_id",)
    assert audit_events_trace_id is not None
    assert audit_events_trace_id.foreign_key == "query_history.trace_id"
    assert agent_traces_trace_id is not None
    assert agent_traces_trace_id.foreign_key == "query_history.trace_id"


def test_hot_audit_and_history_data_retention_is_at_least_180_days() -> None:
    catalog = build_default_data_model_catalog()

    query_history = catalog.get_table("query_history")
    audit_events = catalog.get_table("audit_events")

    assert query_history is not None
    assert query_history.retention_days == 180
    assert audit_events is not None
    assert audit_events.retention_days == 180


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
