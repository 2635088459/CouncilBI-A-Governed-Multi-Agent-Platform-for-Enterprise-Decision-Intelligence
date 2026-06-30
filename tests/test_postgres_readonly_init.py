from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
READONLY_INIT_SQL = REPO_ROOT / "docker" / "postgres" / "init" / "01-readonly-role.sql"


def test_postgres_readonly_init_script_creates_readonly_role() -> None:
    sql = " ".join(READONLY_INIT_SQL.read_text(encoding="utf-8").split())

    assert "CREATE SCHEMA IF NOT EXISTS business" in sql
    assert "CREATE ROLE chatbi_readonly LOGIN PASSWORD 'chatbi_readonly_password'" in sql
    assert "GRANT USAGE ON SCHEMA business TO chatbi_readonly" in sql
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA business TO chatbi_readonly" in sql
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA business GRANT SELECT ON TABLES TO chatbi_readonly" in sql
    assert "ALTER ROLE chatbi_readonly SET search_path = business, public" in sql
    assert "GRANT INSERT" not in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql
