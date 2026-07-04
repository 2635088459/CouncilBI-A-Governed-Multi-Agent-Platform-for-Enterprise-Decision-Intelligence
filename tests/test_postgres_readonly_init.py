from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
READONLY_INIT_SCRIPT = REPO_ROOT / "docker" / "postgres" / "init" / "01-readonly-role.sh"


def test_postgres_readonly_init_script_creates_readonly_role() -> None:
    script = " ".join(READONLY_INIT_SCRIPT.read_text(encoding="utf-8").split())

    assert "CHATBI_READONLY_PASSWORD is required" in script
    assert "CREATE SCHEMA IF NOT EXISTS business" in script
    assert "CREATE ROLE chatbi_readonly LOGIN" in script
    assert "ALTER ROLE chatbi_readonly WITH PASSWORD :'readonly_password'" in script
    assert "GRANT USAGE ON SCHEMA business TO chatbi_readonly" in script
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA business TO chatbi_readonly" in script
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA business GRANT SELECT ON TABLES TO chatbi_readonly" in script
    assert "ALTER ROLE chatbi_readonly SET search_path = business, public" in script
    assert "chatbi_readonly_password" not in script
    assert "GRANT INSERT" not in script
    assert "GRANT UPDATE" not in script
    assert "GRANT DELETE" not in script
