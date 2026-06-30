from pathlib import Path
import tomllib


def test_frontend_static_build_cli_is_packaged() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    scripts = project["project"]["scripts"]

    assert scripts["chatbi-build-frontend"] == "chatbi.frontend.build_static:main"
