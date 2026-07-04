from pathlib import Path
import re
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[1]


FINAL_ARTIFACTS = (
    "docs/api.md",
    "docs/local-startup.md",
    "docs/deployment/cloud-kubernetes-runbook.md",
    "docs/demo-script.md",
    "docs/risk-register.md",
    "verification/12-final-submission-package-verification.md",
    "spec/final-version/en/README.en.md",
    "spec/final-version/zh-CN/README.zh-CN.md",
    "system_design/final-version/en/README.en.md",
    "system_design/final-version/zh-CN/README.zh-CN.md",
)


def read_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_root_readme_links_all_final_submission_artifacts() -> None:
    readme = read_text("README.md")

    for relative_path in FINAL_ARTIFACTS:
        assert f"]({relative_path})" in readme or f"]({relative_path.rstrip('/')}/)" in readme


def test_final_api_docs_cover_required_endpoint_families() -> None:
    text = read_text("docs/api.md")

    for heading in ("## Auth", "## Chat", "## RAG And Documents", "## Admin", "## Evaluation", "## Observability"):
        assert heading in text
    for endpoint in (
        "/api/v2/auth/login",
        "/api/v2/chat/query",
        "/api/v2/documents/index",
        "/api/v2/admin/observability/summary",
        "/api/v2/evals/run",
        "/healthz",
        "/readyz",
        "/metrics",
    ):
        assert endpoint in text


def test_local_startup_guide_documents_services_env_seed_tests_and_demo() -> None:
    text = read_text("docs/local-startup.md")

    for expected in (
        "POSTGRES_PASSWORD",
        "CHATBI_READONLY_PASSWORD",
        "docker compose up --build",
        "chatbi.final_seed",
        "python -m pytest",
        "demo-script.md",
    ):
        assert expected in text


def test_demo_script_covers_user_and_admin_acceptance_flows() -> None:
    text = read_text("docs/demo-script.md")

    for expected in (
        "Sign In",
        "User Chat Flow",
        "RAG Citation Flow",
        "Admin Observability Flow",
        "Release Gate Flow",
        "/api/v2/admin/observability/summary",
    ):
        assert expected in text
    assert "15 minutes" in text


def test_risk_register_makes_known_gaps_explicit() -> None:
    text = read_text("docs/risk-register.md")

    for expected in ("Open", "Partial", "No live staging cluster", "External APM backend", "Production vector database"):
        assert expected in text


def test_final_verification_report_lists_machine_gates_and_mock_llm_policy() -> None:
    text = read_text("verification/12-final-submission-package-verification.md")

    for expected in (
        "pyright",
        "pytest",
        "test_release_gate.py",
        "test_cloud_secret_scan.py",
        "test_runtime_latency_smoke.py",
        "mock/deterministic providers",
        "OPENAI_API_KEY",
    ):
        assert expected in text


def test_final_docs_and_specs_have_english_chinese_numbered_parity() -> None:
    for root in ("spec/final-version", "system_design/final-version"):
        en_numbers = _numbered_file_prefixes(REPO_ROOT / root / "en")
        zh_numbers = _numbered_file_prefixes(REPO_ROOT / root / "zh-CN")
        assert en_numbers == zh_numbers


def test_final_markdown_links_are_relative() -> None:
    markdown_files = (
        "README.md",
        "docs/api.md",
        "docs/local-startup.md",
        "docs/demo-script.md",
        "docs/risk-register.md",
        "docs/deployment/cloud-kubernetes-runbook.md",
        "verification/12-final-submission-package-verification.md",
    )
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for relative_path in markdown_files:
        text = read_text(relative_path)
        for match in link_pattern.finditer(text):
            target = match.group(1)
            assert not target.startswith(("http://", "https://", "file://")), relative_path
            if target.startswith("#"):
                continue
            assert not target.startswith("/"), relative_path


def test_final_markdown_local_links_resolve_to_existing_files_or_directories() -> None:
    markdown_paths = (
        REPO_ROOT / "README.md",
        *(REPO_ROOT / "docs").rglob("*.md"),
        *(REPO_ROOT / "spec" / "final-version").rglob("*.md"),
        *(REPO_ROOT / "system_design" / "final-version").rglob("*.md"),
        *(REPO_ROOT / "verification").glob("*.md"),
    )
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for markdown_path in markdown_paths:
        text = markdown_path.read_text(encoding="utf-8")
        for match in link_pattern.finditer(text):
            raw_target = match.group(1).strip()
            if raw_target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target_without_anchor = raw_target.split("#", 1)[0]
            if not target_without_anchor:
                continue
            resolved = (markdown_path.parent / unquote(target_without_anchor)).resolve()
            assert resolved.exists(), f"{markdown_path.relative_to(REPO_ROOT)} -> {raw_target}"


def _numbered_file_prefixes(directory: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.name[:2]
            for path in directory.iterdir()
            if path.is_file() and path.name[:2].isdigit()
        )
    )
