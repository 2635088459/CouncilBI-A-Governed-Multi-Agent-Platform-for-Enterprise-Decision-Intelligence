from chatbi.governance.business_table_catalog import BusinessTableCatalog, resolve_federated_pg_context


class _FakeConnection:
    """Fakes the ``business`` schema + ``governance.access_policies`` seed data.

    Tables: revenue_by_month(month, revenue), campaigns(campaign_id, month,
    spend). Policies: revenue_by_month.revenue is an explicit P2 allow (not
    denied by absence); campaigns has no policy rows at all (also allowed,
    since column visibility here is deny-list style); a made-up
    customers.customer_id P0-deny row proves the deny path works.
    """

    def __init__(self) -> None:
        self.queries: list[str] = []

    def cursor(self) -> _FakeCursor:
        # A single fake cursor object is fine since each call site issues
        # exactly one query and immediately reads its own result.
        return _RoutingCursor(self)


class _RoutingCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection
        self._rows: list[tuple[object, ...]] = []

    def __enter__(self) -> "_RoutingCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self._connection.queries.append(sql)
        if "information_schema.tables" in sql:
            self._rows = [("campaigns",), ("revenue_by_month",)]
        elif "information_schema.columns" in sql:
            table_name = params[0]
            if table_name == "revenue_by_month":
                self._rows = [("month",), ("revenue",)]
            elif table_name == "campaigns":
                self._rows = [("campaign_id",), ("month",), ("spend",)]
            else:
                self._rows = []
        elif "access_policies" in sql:
            table_name = params[0]
            if table_name == "revenue_by_month":
                self._rows = [("revenue", ["admin", "analyst", "viewer"], "allow")]
            else:
                self._rows = []
        else:
            self._rows = []

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


def test_business_table_names_reads_from_information_schema() -> None:
    catalog = BusinessTableCatalog(_FakeConnection())

    names = catalog.business_table_names()

    assert names == ("campaigns", "revenue_by_month")


def test_table_columns_reads_from_information_schema() -> None:
    catalog = BusinessTableCatalog(_FakeConnection())

    columns = catalog.table_columns("revenue_by_month")

    assert columns == ("month", "revenue")


def test_safe_columns_for_role_allows_unclassified_columns_by_default() -> None:
    """campaigns has zero access_policies rows; deny-list style means every
    column is readable, not zero (which an allow-list interpretation would
    wrongly produce)."""

    catalog = BusinessTableCatalog(_FakeConnection())

    columns = catalog.safe_columns_for_role("campaigns", "analyst")

    assert columns == ("campaign_id", "month", "spend")


def test_safe_columns_for_role_keeps_an_explicit_p2_allow_column() -> None:
    catalog = BusinessTableCatalog(_FakeConnection())

    columns = catalog.safe_columns_for_role("revenue_by_month", "analyst")

    assert columns == ("month", "revenue")


class _DenyRowConnection:
    """A table with one explicit deny row, to prove denial actually excludes a column."""

    def cursor(self) -> "_DenyRowCursor":
        return _DenyRowCursor()


class _DenyRowCursor:
    def __enter__(self) -> "_DenyRowCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self._sql = sql
        self._params = params

    def fetchall(self) -> list[tuple[object, ...]]:
        if "information_schema.columns" in self._sql:
            return [("customer_id",), ("region",)]
        if "access_policies" in self._sql:
            return [("customer_id", ["admin"], "deny")]
        return []


def test_safe_columns_for_role_excludes_an_explicit_deny_column_for_non_admin() -> None:
    catalog = BusinessTableCatalog(_DenyRowConnection())

    columns = catalog.safe_columns_for_role("customer_orders", "analyst")

    assert columns == ("region",)


def test_safe_columns_for_role_allows_admin_through_an_allowed_roles_deny_row() -> None:
    catalog = BusinessTableCatalog(_DenyRowConnection())

    columns = catalog.safe_columns_for_role("customer_orders", "admin")

    assert columns == ("customer_id", "region")


def test_resolve_federated_pg_context_matches_underscored_table_name() -> None:
    catalog = BusinessTableCatalog(_FakeConnection())

    context = resolve_federated_pg_context(
        "Compare my file to revenue_by_month please", "analyst", catalog
    )

    assert context is not None
    assert context.table_name == "revenue_by_month"
    assert context.columns == ("month", "revenue")


def test_resolve_federated_pg_context_matches_spaced_table_name() -> None:
    catalog = BusinessTableCatalog(_FakeConnection())

    context = resolve_federated_pg_context(
        "Join my file with the revenue by month table", "analyst", catalog
    )

    assert context is not None
    assert context.table_name == "revenue_by_month"


def test_resolve_federated_pg_context_returns_none_when_no_table_is_named() -> None:
    catalog = BusinessTableCatalog(_FakeConnection())

    context = resolve_federated_pg_context(
        "What is my forecast revenue for next quarter?", "analyst", catalog
    )

    assert context is None
