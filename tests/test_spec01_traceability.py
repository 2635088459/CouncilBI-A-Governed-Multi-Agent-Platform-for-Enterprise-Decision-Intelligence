import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EN_SPEC_PATH = ROOT / "spec" / "final-version" / "en" / "01-auth-rbac-tenant-isolation.spec.en.md"
ZH_SPEC_PATH = (
    ROOT
    / "spec"
    / "final-version"
    / "zh-CN"
    / "01-auth-rbac-tenant-isolation.spec.zh-CN.md"
)
SPEC_INDEX_PATH = ROOT / "spec" / "index.md"
EN_README_PATH = ROOT / "spec" / "final-version" / "en" / "README.en.md"
ZH_README_PATH = ROOT / "spec" / "final-version" / "zh-CN" / "README.zh-CN.md"


@pytest.mark.parametrize(
    ("path", "headings"),
    (
        (
            EN_SPEC_PATH,
            {
                "requirements": ("## 4. Functional Requirements", "## 6. Contracts"),
                "acceptance": ("## 7. Acceptance Criteria", "## 8. Test Plan"),
                "tests": ("## 8. Test Plan", "## 9. Traceability Matrix"),
                "traceability": ("## 9. Traceability Matrix", "## 10. Implementation Notes"),
            },
        ),
        (
            ZH_SPEC_PATH,
            {
                "requirements": ("## 4. 功能需求", "## 6. 契约"),
                "acceptance": ("## 7. 验收标准", "## 8. 测试计划"),
                "tests": ("## 8. 测试计划", "## 9. 追踪矩阵"),
                "traceability": ("## 9. 追踪矩阵", "## 10. 实现说明"),
            },
        ),
    ),
)
def test_spec01_traceability_matrix_references_every_requirement_ac_and_test_case(
    path: Path,
    headings: dict[str, tuple[str, str]],
) -> None:
    text = path.read_text(encoding="utf-8")
    requirement_ids = _ids_in_section(
        text,
        *headings["requirements"],
        r"(?:FR|NFR)-FV01-\d{3}",
    )
    acceptance_ids = _ids_in_section(
        text,
        *headings["acceptance"],
        r"AC-FV01-\d{3}",
    )
    test_case_ids = _ids_in_section(
        text,
        *headings["tests"],
        r"TC-FV01-\d{3}",
    )
    traceability = _section(
        text,
        *headings["traceability"],
    )

    traced_requirement_ids = set(re.findall(r"(?:FR|NFR)-FV01-\d{3}", traceability))
    traced_acceptance_ids = set(re.findall(r"AC-FV01-\d{3}", traceability))
    traced_test_case_ids = set(re.findall(r"TC-FV01-\d{3}", traceability))

    assert requirement_ids <= traced_requirement_ids
    assert acceptance_ids <= traced_acceptance_ids
    assert test_case_ids <= traced_test_case_ids


def test_spec01_english_and_chinese_specs_have_matching_ids() -> None:
    english_text = EN_SPEC_PATH.read_text(encoding="utf-8")
    chinese_text = ZH_SPEC_PATH.read_text(encoding="utf-8")

    id_pattern = r"(?:FR|NFR|AC|TC)-FV01-\d{3}"

    assert set(re.findall(id_pattern, chinese_text)) == set(
        re.findall(id_pattern, english_text)
    )


def test_spec01_indexes_mark_auth_rbac_tenant_isolation_as_verified() -> None:
    for path in (SPEC_INDEX_PATH, EN_README_PATH, ZH_README_PATH):
        text = path.read_text(encoding="utf-8")
        matching_lines = [
            line
            for line in text.splitlines()
            if "01-auth-rbac-tenant-isolation" in line
            or "Auth, RBAC, and Tenant Isolation" in line
            or "Auth、RBAC 与多租户隔离" in line
        ]

        assert matching_lines
        assert any("Verified/Implemented" in line for line in matching_lines)


def _ids_in_section(
    text: str,
    start_heading: str,
    end_heading: str,
    pattern: str,
) -> set[str]:
    return set(re.findall(pattern, _section(text, start_heading, end_heading)))


def _section(text: str, start_heading: str, end_heading: str) -> str:
    start = text.index(start_heading)
    end = text.index(end_heading, start)
    return text[start:end]
