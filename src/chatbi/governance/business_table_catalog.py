"""Live `business` schema introspection for FederatedQueryAgent (FR-FV10-021).

Deliberately reads live Postgres state (``information_schema`` +
``governance.access_policies``) instead of the static ``DataModelCatalog`` in
``chatbi.data_model``: that catalog describes an aspirational schema (orders,
customers, refunds, ...) that does not match what this project actually
deploys under the ``business`` schema (``campaigns``, ``revenue_by_month``,
``support_ticket_summary``). Generating federated-join SQL from the static
catalog would reference tables that do not exist.

Column visibility is deny-list style, matching how
``scripts/seed_demo_data.sql`` actually populates ``access_policies``: only
sensitive fields get an explicit ``deny``/``mask`` row (e.g.
``customers.customer_id``), so a column with no matching row is treated as
safe. A ``mask`` row is treated the same as ``deny`` here because this path
has no per-value masking step after the DuckDB join runs.
"""

from __future__ import annotations

from typing import Any, Protocol

from chatbi.files.contracts import PostgresQueryContext


class BusinessCatalogConnection(Protocol):
    def cursor(self) -> Any: ...


class BusinessTableCatalog:
    """Reads real ``business.*`` tables/columns and their access policies."""

    def __init__(self, connection: BusinessCatalogConnection) -> None:
        self._connection = connection

    def business_table_names(self) -> tuple[str, ...]:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'business' ORDER BY table_name"
            )
            return tuple(row[0] for row in cur.fetchall())

    def table_columns(self, table_name: str) -> tuple[str, ...]:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'business' AND table_name = %s "
                "ORDER BY ordinal_position",
                (table_name,),
            )
            return tuple(row[0] for row in cur.fetchall())

    def safe_columns_for_role(self, table_name: str, role: str) -> tuple[str, ...]:
        """This table's columns that ``role`` may read for a federated join."""

        all_columns = self.table_columns(table_name)
        denied = self._denied_columns(table_name, role)
        return tuple(column for column in all_columns if column not in denied)

    def _denied_columns(self, table_name: str, role: str) -> frozenset[str]:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT field_name, allowed_roles, action FROM governance.access_policies "
                "WHERE object_name IN (%s, %s) AND action IN ('deny', 'mask')",
                (table_name, f"business.{table_name}"),
            )
            denied: set[str] = set()
            for field_name, allowed_roles, action in cur.fetchall():
                if action == "mask" or role not in (allowed_roles or ()):
                    denied.add(field_name)
            return frozenset(denied)


def resolve_federated_pg_context(
    question: str,
    role: str,
    catalog: BusinessTableCatalog,
    *,
    max_rows: int = 500,
) -> PostgresQueryContext | None:
    """Best-effort: find one real business table this question plausibly means.

    Matches only if the question mentions the table's name (underscored or
    spaced). Returns ``None`` on no match, no readable columns, or any
    lookup failure, so the caller can fall back to a file-only answer
    instead of guessing which table to join.
    """

    normalized = question.lower()
    try:
        table_names = catalog.business_table_names()
    except Exception:
        return None

    for table_name in table_names:
        display_name = table_name.replace("_", " ")
        if table_name not in normalized and display_name not in normalized:
            continue
        try:
            safe_columns = catalog.safe_columns_for_role(table_name, role)
        except Exception:
            continue
        if not safe_columns:
            continue
        return PostgresQueryContext(table_name=table_name, columns=safe_columns, max_rows=max_rows)

    return None
