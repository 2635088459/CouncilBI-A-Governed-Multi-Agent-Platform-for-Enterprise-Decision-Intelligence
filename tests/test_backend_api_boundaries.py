import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_API_CONTROLLER = PROJECT_ROOT / "src" / "chatbi" / "api" / "http.py"
SQL_STATEMENT_PREFIXES = (
    "select ",
    "insert ",
    "update ",
    "delete ",
    "create ",
    "drop ",
    "alter ",
    "grant ",
    "revoke ",
)


def test_backend_api_controller_does_not_execute_raw_sql_directly() -> None:
    tree = ast.parse(BACKEND_API_CONTROLLER.read_text())

    direct_execute_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany", "execute_batch"}
    ]

    assert direct_execute_calls == []


def test_backend_api_controller_does_not_embed_raw_sql_statements() -> None:
    tree = ast.parse(BACKEND_API_CONTROLLER.read_text())

    raw_sql_literals = [
        (node.lineno, node.value.strip())
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.strip().lower().startswith(SQL_STATEMENT_PREFIXES)
    ]

    assert raw_sql_literals == []
