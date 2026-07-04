import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_semantic_contracts_pass_pyright() -> None:
    pyright = shutil.which("pyright")
    if pyright is None:
        local_pyright = Path(sys.executable).resolve().parent / "pyright"
        if not local_pyright.exists():
            local_pyright = REPO_ROOT / ".venv" / "bin" / "pyright"
        if local_pyright.exists():
            pyright = str(local_pyright)
    if pyright is None:
        pytest.skip("pyright is required for semantic contract type checks.")

    result = subprocess.run(
        [
            pyright,
            "src/chatbi/semantic",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
