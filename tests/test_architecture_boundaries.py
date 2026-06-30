import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "chatbi"

EXECUTOR_MODULE = "chatbi.orchestration.executor"
EXECUTOR_ALLOWED_PARTS = {
    "agents",
    "orchestration",
}

FRONTEND_FORBIDDEN_PREFIXES = (
    "chatbi.agents",
    "chatbi.governance",
    "chatbi.history",
    "chatbi.orchestration",
    "chatbi.semantic",
)


def python_files() -> tuple[Path, ...]:
    return tuple(sorted(SRC_ROOT.rglob("*.py")))


def imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)
    return tuple(imports)


def package_part(path: Path) -> str:
    relative = path.relative_to(SRC_ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else "__root__"


def test_query_executor_is_not_imported_by_public_or_frontend_layers() -> None:
    violations: list[str] = []
    for path in python_files():
        if EXECUTOR_MODULE not in imported_modules(path):
            continue
        if package_part(path) in EXECUTOR_ALLOWED_PARTS:
            continue
        violations.append(str(path.relative_to(REPO_ROOT)))

    assert violations == []


def test_frontend_does_not_import_backend_internal_layers() -> None:
    violations: list[str] = []
    frontend_root = SRC_ROOT / "frontend"
    for path in sorted(frontend_root.rglob("*.py")):
        for imported in imported_modules(path):
            if imported.startswith(FRONTEND_FORBIDDEN_PREFIXES):
                violations.append(f"{path.relative_to(REPO_ROOT)} imports {imported}")

    assert violations == []
