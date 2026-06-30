"""Build static frontend assets for deployment.

The real browser application can be bundled by React, Vue, Svelte, or another
tool later. This module owns the stable deployment contract: an ``index.html``
file with browser-safe runtime configuration injected into it.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
from typing import Mapping, Sequence, TextIO

from chatbi.frontend.runtime_config import (
    FrontendRuntimeConfig,
    parse_frontend_runtime_config,
)
from chatbi.frontend.static_bootstrap import build_static_index_html

_STATIC_ASSET_DIR = Path(__file__).with_name("static_assets")
_DEFAULT_STATIC_ASSETS = ("app.js", "styles.css")


@dataclass(frozen=True, slots=True)
class StaticFrontendAssetManifest:
    output_dir: Path
    index_html_path: Path
    files_written: tuple[Path, ...]
    runtime_environment: str
    locale_default: str


def build_static_frontend_assets(
    output_dir: Path,
    config: FrontendRuntimeConfig,
    *,
    title: str = "Governed ChatBI",
    app_script_src: str = "/assets/app.js",
    stylesheet_src: str = "/assets/styles.css",
    asset_names: Iterable[str] = _DEFAULT_STATIC_ASSETS,
) -> StaticFrontendAssetManifest:
    """Write the static frontend entrypoint and return a small build manifest."""

    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    index_html_path = output_dir / "index.html"
    index_html = build_static_index_html(
        config,
        title=title,
        app_script_src=app_script_src,
        stylesheet_src=stylesheet_src,
    )
    index_html_path.write_text(index_html, encoding="utf-8")
    asset_paths = tuple(_copy_static_asset(asset_name, assets_dir) for asset_name in asset_names)
    return StaticFrontendAssetManifest(
        output_dir=output_dir,
        index_html_path=index_html_path,
        files_written=(index_html_path, *asset_paths),
        runtime_environment=config.environment,
        locale_default=config.locale_default,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m chatbi.frontend.build_static",
        description="Build browser-safe static assets for the ChatBI frontend.",
    )
    parser.add_argument(
        "--output-dir",
        default="dist/frontend",
        help="Directory where index.html will be written.",
    )
    parser.add_argument(
        "--api-base-url",
        default=None,
        help="Public Backend API base URL. Defaults to frontend runtime env.",
    )
    parser.add_argument(
        "--environment",
        default=None,
        choices=("dev", "staging", "prod"),
        help="Frontend runtime environment. Defaults to frontend runtime env.",
    )
    parser.add_argument(
        "--locale-default",
        default=None,
        choices=("en", "zh-CN"),
        help="Default frontend locale. Defaults to frontend runtime env.",
    )
    parser.add_argument(
        "--title",
        default="Governed ChatBI",
        help="HTML document title.",
    )
    parser.add_argument(
        "--app-script-src",
        default="/assets/app.js",
        help="Browser app module script path.",
    )
    parser.add_argument(
        "--stylesheet-src",
        default="/assets/styles.css",
        help="Browser stylesheet path.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = build_parser().parse_args(argv)
    runtime_env = env or os.environ

    try:
        config = parse_frontend_runtime_config(
            {
                "api_base_url": args.api_base_url
                or _first_present(
                    runtime_env,
                    "CHATBI_FRONTEND_API_BASE_URL",
                    "API_BASE_URL",
                    "BACKEND_API_URL",
                ),
                "environment": args.environment
                or _first_present(
                    runtime_env,
                    "CHATBI_FRONTEND_ENVIRONMENT",
                    "FRONTEND_ENVIRONMENT",
                ),
                "locale_default": args.locale_default
                or _first_present(
                    runtime_env,
                    "CHATBI_FRONTEND_LOCALE_DEFAULT",
                    "FRONTEND_LOCALE_DEFAULT",
                ),
            }
        )
        manifest = build_static_frontend_assets(
            Path(args.output_dir),
            config,
            title=args.title,
            app_script_src=args.app_script_src,
            stylesheet_src=args.stylesheet_src,
        )
    except ValueError as exc:
        print(f"Frontend static build config error: {exc}", file=stderr)
        return 2
    except OSError as exc:
        print(f"Frontend static build failed: {exc.__class__.__name__}", file=stderr)
        return 1

    print(f"Wrote frontend index: {manifest.index_html_path}", file=stdout)
    return 0


def _copy_static_asset(asset_name: str, assets_dir: Path) -> Path:
    if "/" in asset_name or "\\" in asset_name or asset_name in {"", ".", ".."}:
        raise ValueError(f"Invalid static asset name: {asset_name}")
    source_path = _STATIC_ASSET_DIR / asset_name
    target_path = assets_dir / asset_name
    shutil.copyfile(source_path, target_path)
    return target_path


def _first_present(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None:
            return value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
