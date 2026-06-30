from chatbi.governance import SqlHasher


def test_sql_hasher_returns_standard_sha256_hex_digest() -> None:
    sql_hash = SqlHasher().hash("SELECT * FROM orders")

    assert sql_hash == "ecf344c50257470a15b80909610cfa2b82e96248515f7770b184db5e19149908"
    assert len(sql_hash) == 64


def test_sql_hasher_is_deterministic() -> None:
    hasher = SqlHasher()

    first_hash = hasher.hash("SELECT month, revenue FROM revenue_by_month")
    second_hash = hasher.hash("SELECT month, revenue FROM revenue_by_month")

    assert first_hash == second_hash


def test_sql_hasher_changes_when_sql_text_changes() -> None:
    hasher = SqlHasher()

    first_hash = hasher.hash("SELECT * FROM orders")
    second_hash = hasher.hash("SELECT * FROM customers")

    assert first_hash != second_hash
