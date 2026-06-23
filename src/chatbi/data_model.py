"""MVP data model catalog for business, knowledge, and governance tables.

The catalog is metadata first: it describes the tables, fields, metrics,
partitions, and quality rules that other layers should obey. Later we can use
the same metadata to generate DDL or configure a real warehouse.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataDomain(StrEnum):
    BUSINESS_ANALYTICS = "business_analytics"
    SEMANTIC_GOVERNANCE = "semantic_governance"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    RUNTIME_GOVERNANCE = "runtime_governance"
    CONFIG_CACHE = "config_cache"


class SensitivityClass(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class QualityRuleType(StrEnum):
    NON_NULL = "non_null"
    NON_NEGATIVE = "non_negative"
    PARTITION_REQUIRED = "partition_required"
    RETENTION_REQUIRED = "retention_required"


@dataclass(frozen=True, slots=True)
class ColumnDefinition:
    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    sensitivity: SensitivityClass | None = None
    foreign_key: str | None = None

    @property
    def is_p0(self) -> bool:
        return self.sensitivity is SensitivityClass.P0

    @property
    def is_p1(self) -> bool:
        return self.sensitivity is SensitivityClass.P1


@dataclass(frozen=True, slots=True)
class QualityRuleDefinition:
    rule_type: QualityRuleType
    column_name: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class TableDefinition:
    name: str
    domain: DataDomain
    columns: tuple[ColumnDefinition, ...]
    partition_column: str | None = None
    indexes: tuple[tuple[str, ...], ...] = ()
    retention_days: int | None = None
    quality_rules: tuple[QualityRuleDefinition, ...] = ()

    def get_column(self, column_name: str) -> ColumnDefinition | None:
        for column in self.columns:
            if column.name == column_name:
                return column
        return None

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns if column.is_primary_key)

    @property
    def is_partitioned(self) -> bool:
        return self.partition_column is not None


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    sql_definition: str
    source_tables: tuple[str, ...]
    semantic_version: str


class DataModelCatalog:
    """Registry of tables, metrics, and sensitivity classifications."""

    def __init__(
        self,
        tables: tuple[TableDefinition, ...],
        metrics: tuple[MetricDefinition, ...] = (),
    ) -> None:
        self._tables_by_name: dict[str, TableDefinition] = {}
        for table in tables:
            self._tables_by_name[table.name] = table

        self._metrics_by_name: dict[str, MetricDefinition] = {}
        for metric in metrics:
            self._metrics_by_name[metric.name] = metric

    def get_table(self, table_name: str) -> TableDefinition | None:
        return self._tables_by_name.get(table_name)

    def table_names(self) -> tuple[str, ...]:
        return tuple(self._tables_by_name.keys())

    def table_names_for_domain(self, domain: DataDomain) -> tuple[str, ...]:
        return tuple(
            table.name
            for table in self._tables_by_name.values()
            if table.domain is domain
        )

    def business_table_names(self) -> tuple[str, ...]:
        return self.table_names_for_domain(DataDomain.BUSINESS_ANALYTICS)

    def get_column(self, table_name: str, column_name: str) -> ColumnDefinition | None:
        table = self.get_table(table_name)
        if table is None:
            return None
        return table.get_column(column_name)

    def get_metric(self, metric_name: str) -> MetricDefinition | None:
        return self._metrics_by_name.get(metric_name)

    def metric_names(self) -> tuple[str, ...]:
        return tuple(self._metrics_by_name.keys())

    def partitioned_table_names(self) -> tuple[str, ...]:
        return tuple(
            table.name
            for table in self._tables_by_name.values()
            if table.is_partitioned
        )

    def quality_rules_for_table(self, table_name: str) -> tuple[QualityRuleDefinition, ...]:
        table = self.get_table(table_name)
        if table is None:
            return ()
        return table.quality_rules

    def p0_fields(self) -> tuple[str, ...]:
        return self._fields_for_sensitivity(SensitivityClass.P0)

    def p1_fields(self) -> tuple[str, ...]:
        return self._fields_for_sensitivity(SensitivityClass.P1)

    def _fields_for_sensitivity(self, sensitivity: SensitivityClass) -> tuple[str, ...]:
        fields: list[str] = []
        for table in self._tables_by_name.values():
            for column in table.columns:
                if column.sensitivity is sensitivity:
                    fields.append(f"{table.name}.{column.name}")
        return tuple(fields)


def _non_null_primary_key_rules(columns: tuple[ColumnDefinition, ...]) -> tuple[QualityRuleDefinition, ...]:
    return tuple(
        QualityRuleDefinition(
            rule_type=QualityRuleType.NON_NULL,
            column_name=column.name,
            description=f"{column.name} must be present for every row.",
        )
        for column in columns
        if column.is_primary_key
    )


def _money_rule(column_name: str) -> QualityRuleDefinition:
    return QualityRuleDefinition(
        rule_type=QualityRuleType.NON_NEGATIVE,
        column_name=column_name,
        description=f"{column_name} cannot be negative.",
    )


def _partition_rule(column_name: str) -> QualityRuleDefinition:
    return QualityRuleDefinition(
        rule_type=QualityRuleType.PARTITION_REQUIRED,
        column_name=column_name,
        description=f"Large fact table scans should prune by {column_name}.",
    )


def _retention_rule(days: int) -> QualityRuleDefinition:
    return QualityRuleDefinition(
        rule_type=QualityRuleType.RETENTION_REQUIRED,
        description=f"Hot records must be retained for at least {days} days.",
    )


def build_default_data_model_catalog() -> DataModelCatalog:
    orders = _build_orders_table()
    refunds = _build_refunds_table()
    customers = _build_customers_table()
    products = _build_products_table()
    regions = _build_regions_table()
    web_events = _build_web_events_table()
    support_tickets = _build_support_tickets_table()
    marketing_campaigns = _build_marketing_campaigns_table()

    return DataModelCatalog(
        tables=(
            orders,
            refunds,
            customers,
            products,
            regions,
            web_events,
            support_tickets,
            marketing_campaigns,
            *_build_semantic_governance_tables(),
            *_build_knowledge_retrieval_tables(),
            *_build_runtime_governance_tables(),
            *_build_config_cache_tables(),
        ),
        metrics=_build_core_metrics(),
    )


def _build_orders_table() -> TableDefinition:
    columns = (
        ColumnDefinition("order_id", "bigint", nullable=False, is_primary_key=True),
        ColumnDefinition(
            "customer_id",
            "bigint",
            nullable=False,
            sensitivity=SensitivityClass.P0,
            foreign_key="customers.customer_id",
        ),
        ColumnDefinition("product_id", "bigint", nullable=False, foreign_key="products.product_id"),
        ColumnDefinition("region_id", "string", nullable=False, foreign_key="regions.region_id"),
        ColumnDefinition("order_amount", "decimal", nullable=False),
        ColumnDefinition("status", "string", nullable=False),
        ColumnDefinition("order_date", "datetime", nullable=False),
    )
    return TableDefinition(
        name="orders",
        domain=DataDomain.BUSINESS_ANALYTICS,
        partition_column="order_date",
        indexes=(("order_date", "status"), ("region_id", "product_id")),
        columns=columns,
        quality_rules=(
            *_non_null_primary_key_rules(columns),
            _money_rule("order_amount"),
            _partition_rule("order_date"),
        ),
    )


def _build_refunds_table() -> TableDefinition:
    columns = (
        ColumnDefinition("refund_id", "bigint", nullable=False, is_primary_key=True),
        ColumnDefinition("order_id", "bigint", nullable=False, foreign_key="orders.order_id"),
        ColumnDefinition("refund_amount", "decimal", nullable=False),
        ColumnDefinition("refund_date", "datetime", nullable=False),
        ColumnDefinition("reason", "string"),
    )
    return TableDefinition(
        name="refunds",
        domain=DataDomain.BUSINESS_ANALYTICS,
        partition_column="refund_date",
        indexes=(("refund_date", "order_id"),),
        columns=columns,
        quality_rules=(
            *_non_null_primary_key_rules(columns),
            _money_rule("refund_amount"),
            _partition_rule("refund_date"),
        ),
    )


def _build_customers_table() -> TableDefinition:
    columns = (
        ColumnDefinition("customer_id", "bigint", nullable=False, is_primary_key=True, sensitivity=SensitivityClass.P0),
        ColumnDefinition("customer_name", "string", sensitivity=SensitivityClass.P1),
        ColumnDefinition("user_email", "string", sensitivity=SensitivityClass.P1),
        ColumnDefinition("phone", "string", sensitivity=SensitivityClass.P1),
        ColumnDefinition("region_id", "string", foreign_key="regions.region_id"),
        ColumnDefinition("created_at", "datetime", nullable=False),
    )
    return TableDefinition(
        name="customers",
        domain=DataDomain.BUSINESS_ANALYTICS,
        columns=columns,
        quality_rules=_non_null_primary_key_rules(columns),
    )


def _build_products_table() -> TableDefinition:
    columns = (
        ColumnDefinition("product_id", "bigint", nullable=False, is_primary_key=True),
        ColumnDefinition("product_name", "string", nullable=False),
        ColumnDefinition("category", "string", nullable=False),
        ColumnDefinition("price", "decimal", nullable=False),
    )
    return TableDefinition(
        name="products",
        domain=DataDomain.BUSINESS_ANALYTICS,
        columns=columns,
        quality_rules=(
            *_non_null_primary_key_rules(columns),
            _money_rule("price"),
        ),
    )


def _build_regions_table() -> TableDefinition:
    columns = (
        ColumnDefinition("region_id", "string", nullable=False, is_primary_key=True),
        ColumnDefinition("region_name", "string", nullable=False),
        ColumnDefinition("country", "string", nullable=False),
    )
    return TableDefinition(
        name="regions",
        domain=DataDomain.BUSINESS_ANALYTICS,
        columns=columns,
        quality_rules=_non_null_primary_key_rules(columns),
    )


def _build_web_events_table() -> TableDefinition:
    columns = (
        ColumnDefinition("event_id", "string", nullable=False, is_primary_key=True),
        ColumnDefinition("customer_id", "bigint", sensitivity=SensitivityClass.P0, foreign_key="customers.customer_id"),
        ColumnDefinition("event_type", "string", nullable=False),
        ColumnDefinition("event_time", "datetime", nullable=False),
        ColumnDefinition("campaign_id", "string", foreign_key="marketing_campaigns.campaign_id"),
    )
    return TableDefinition(
        name="web_events",
        domain=DataDomain.BUSINESS_ANALYTICS,
        partition_column="event_time",
        indexes=(("event_time", "event_type", "customer_id"),),
        columns=columns,
        quality_rules=(
            *_non_null_primary_key_rules(columns),
            _partition_rule("event_time"),
        ),
    )


def _build_support_tickets_table() -> TableDefinition:
    columns = (
        ColumnDefinition("ticket_id", "string", nullable=False, is_primary_key=True),
        ColumnDefinition("customer_id", "bigint", sensitivity=SensitivityClass.P0, foreign_key="customers.customer_id"),
        ColumnDefinition("status", "string", nullable=False),
        ColumnDefinition("created_at", "datetime", nullable=False),
    )
    return TableDefinition(
        name="support_tickets",
        domain=DataDomain.BUSINESS_ANALYTICS,
        columns=columns,
        quality_rules=_non_null_primary_key_rules(columns),
    )


def _build_marketing_campaigns_table() -> TableDefinition:
    columns = (
        ColumnDefinition("campaign_id", "string", nullable=False, is_primary_key=True),
        ColumnDefinition("campaign_name", "string", nullable=False),
        ColumnDefinition("channel", "string", nullable=False),
        ColumnDefinition("start_date", "date", nullable=False),
        ColumnDefinition("end_date", "date"),
    )
    return TableDefinition(
        name="marketing_campaigns",
        domain=DataDomain.BUSINESS_ANALYTICS,
        columns=columns,
        quality_rules=_non_null_primary_key_rules(columns),
    )


def _build_semantic_governance_tables() -> tuple[TableDefinition, ...]:
    return (
        TableDefinition(
            name="metrics_catalog",
            domain=DataDomain.SEMANTIC_GOVERNANCE,
            columns=(
                ColumnDefinition("metric_name", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("sql_definition", "string", nullable=False),
                ColumnDefinition("semantic_version", "string", nullable=False),
            ),
        ),
        TableDefinition(
            name="dimension_catalog",
            domain=DataDomain.SEMANTIC_GOVERNANCE,
            columns=(
                ColumnDefinition("field_name", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("table_name", "string", nullable=False),
                ColumnDefinition("sensitivity", "string", nullable=False),
            ),
        ),
        TableDefinition(
            name="semantic_versions",
            domain=DataDomain.SEMANTIC_GOVERNANCE,
            columns=(
                ColumnDefinition("semantic_version", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("created_at", "datetime", nullable=False),
            ),
        ),
    )


def _build_knowledge_retrieval_tables() -> tuple[TableDefinition, ...]:
    return (
        TableDefinition(
            name="documents",
            domain=DataDomain.KNOWLEDGE_RETRIEVAL,
            columns=(
                ColumnDefinition("source_id", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("title", "string", nullable=False),
                ColumnDefinition("doc_type", "string", nullable=False),
                ColumnDefinition("publish_time", "datetime", nullable=False),
            ),
        ),
        TableDefinition(
            name="doc_chunks",
            domain=DataDomain.KNOWLEDGE_RETRIEVAL,
            columns=(
                ColumnDefinition("chunk_id", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("source_id", "string", nullable=False, foreign_key="documents.source_id"),
                ColumnDefinition("chunk_index", "integer", nullable=False),
                ColumnDefinition("chunk_text", "text", nullable=False),
                ColumnDefinition("metadata", "json"),
            ),
        ),
        TableDefinition(
            name="doc_embeddings",
            domain=DataDomain.KNOWLEDGE_RETRIEVAL,
            columns=(
                ColumnDefinition("embedding_id", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("chunk_id", "string", nullable=False, foreign_key="doc_chunks.chunk_id"),
                ColumnDefinition("embedding_vector", "vector", nullable=False),
            ),
        ),
    )


def _build_runtime_governance_tables() -> tuple[TableDefinition, ...]:
    return (
        TableDefinition(
            name="query_history",
            domain=DataDomain.RUNTIME_GOVERNANCE,
            retention_days=180,
            columns=(
                ColumnDefinition("trace_id", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("user_id", "string", nullable=False),
                ColumnDefinition("question", "text", nullable=False),
                ColumnDefinition("sql_text", "text"),
                ColumnDefinition("status", "string", nullable=False),
                ColumnDefinition("created_at", "datetime", nullable=False),
            ),
            quality_rules=(_retention_rule(180),),
        ),
        TableDefinition(
            name="audit_events",
            domain=DataDomain.RUNTIME_GOVERNANCE,
            retention_days=180,
            columns=(
                ColumnDefinition("audit_event_id", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("trace_id", "string", nullable=False, foreign_key="query_history.trace_id"),
                ColumnDefinition("decision", "string", nullable=False),
                ColumnDefinition("reason", "text"),
                ColumnDefinition("created_at", "datetime", nullable=False),
            ),
            quality_rules=(_retention_rule(180),),
        ),
        TableDefinition(
            name="agent_traces",
            domain=DataDomain.RUNTIME_GOVERNANCE,
            columns=(
                ColumnDefinition("agent_trace_id", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("trace_id", "string", nullable=False, foreign_key="query_history.trace_id"),
                ColumnDefinition("agent_name", "string", nullable=False),
                ColumnDefinition("status", "string", nullable=False),
                ColumnDefinition("input_summary", "text"),
                ColumnDefinition("output_summary", "text"),
                ColumnDefinition("created_at", "datetime", nullable=False),
            ),
        ),
        TableDefinition(
            name="eval_runs",
            domain=DataDomain.RUNTIME_GOVERNANCE,
            columns=(
                ColumnDefinition("eval_run_id", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("metric_name", "string", nullable=False),
                ColumnDefinition("score", "decimal", nullable=False),
                ColumnDefinition("created_at", "datetime", nullable=False),
            ),
        ),
    )


def _build_config_cache_tables() -> tuple[TableDefinition, ...]:
    return (
        TableDefinition(
            name="system_configs",
            domain=DataDomain.CONFIG_CACHE,
            columns=(
                ColumnDefinition("config_key", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("config_value", "json", nullable=False),
                ColumnDefinition("updated_at", "datetime", nullable=False),
            ),
        ),
        TableDefinition(
            name="prompt_versions",
            domain=DataDomain.CONFIG_CACHE,
            columns=(
                ColumnDefinition("prompt_version", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("prompt_text", "text", nullable=False),
                ColumnDefinition("created_at", "datetime", nullable=False),
            ),
        ),
        TableDefinition(
            name="cache_keys",
            domain=DataDomain.CONFIG_CACHE,
            columns=(
                ColumnDefinition("cache_key", "string", nullable=False, is_primary_key=True),
                ColumnDefinition("value_digest", "string", nullable=False),
                ColumnDefinition("expires_at", "datetime", nullable=False),
            ),
        ),
    )


def _build_core_metrics() -> tuple[MetricDefinition, ...]:
    return (
        MetricDefinition(
            name="revenue",
            sql_definition="SUM(orders.order_amount) WHERE status='paid'",
            source_tables=("orders",),
            semantic_version="sem_v1",
        ),
        MetricDefinition(
            name="refund_rate",
            sql_definition="SUM(refunds.refund_amount) / SUM(orders.order_amount)",
            source_tables=("refunds", "orders"),
            semantic_version="sem_v1",
        ),
        MetricDefinition(
            name="active_users",
            sql_definition="COUNT(DISTINCT web_events.customer_id) per day",
            source_tables=("web_events",),
            semantic_version="sem_v1",
        ),
        MetricDefinition(
            name="order_count",
            sql_definition="COUNT(DISTINCT orders.order_id)",
            source_tables=("orders",),
            semantic_version="sem_v1",
        ),
    )
