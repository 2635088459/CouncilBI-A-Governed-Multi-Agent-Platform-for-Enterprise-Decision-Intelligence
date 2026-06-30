import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_guardrail_contracts_pass_pyright() -> None:
    pyright = shutil.which("pyright")
    if pyright is None:
        local_pyright = REPO_ROOT / ".venv" / "bin" / "pyright"
        if local_pyright.exists():
            pyright = str(local_pyright)
    if pyright is None:
        pytest.skip("pyright is required for guardrail contract type checks.")

    result = subprocess.run(
        [
            pyright,
            "src/chatbi/governance",
            "tests/test_guardrail_contracts.py",
            "tests/test_v2_guardrail.py",
            "tests/test_guardrail_audit_store.py",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
