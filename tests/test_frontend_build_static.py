from io import StringIO
from pathlib import Path

from chatbi.frontend.build_static import (
    StaticFrontendAssetManifest,
    build_static_frontend_assets,
    main,
)
from chatbi.frontend.runtime_config import FrontendRuntimeConfig


def test_build_static_frontend_assets_writes_index_html(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "dist" / "frontend"
    manifest = build_static_frontend_assets(
        output_dir,
        FrontendRuntimeConfig(
            api_base_url="/api",
            environment="prod",
            locale_default="en",
        ),
    )

    html = manifest.index_html_path.read_text(encoding="utf-8")

    assert isinstance(manifest, StaticFrontendAssetManifest)
    assert manifest.output_dir == output_dir
    assert manifest.index_html_path == output_dir / "index.html"
    assert manifest.files_written == (
        output_dir / "index.html",
        output_dir / "assets" / "app.js",
        output_dir / "assets" / "styles.css",
    )
    assert manifest.runtime_environment == "prod"
    assert manifest.locale_default == "en"
    assert '<main id="chatbi-root" data-app="chatbi"></main>' in html
    assert '<link rel="stylesheet" href="/assets/styles.css">' in html
    assert (output_dir / "assets" / "app.js").exists()
    assert (output_dir / "assets" / "styles.css").exists()
    assert (
        'window.__CHATBI_RUNTIME_CONFIG__={"api_base_url":"/api",'
        '"environment":"prod","locale_default":"en"};'
    ) in html


def test_build_static_frontend_assets_honors_title_and_script_src(
    tmp_path: Path,
) -> None:
    manifest = build_static_frontend_assets(
        tmp_path,
        FrontendRuntimeConfig(
            api_base_url="https://chatbi.example.com/api",
            environment="staging",
            locale_default="zh-CN",
        ),
        title="Enterprise ChatBI",
        app_script_src="/assets/chatbi-app.js",
        stylesheet_src="/assets/chatbi.css",
    )

    html = manifest.index_html_path.read_text(encoding="utf-8")

    assert "<title>Enterprise ChatBI</title>" in html
    assert '<script type="module" src="/assets/chatbi-app.js"></script>' in html
    assert '<link rel="stylesheet" href="/assets/chatbi.css">' in html
    assert '"api_base_url":"https://chatbi.example.com/api"' in html


def test_static_frontend_assets_include_minimum_browser_ui(
    tmp_path: Path,
) -> None:
    manifest = build_static_frontend_assets(
        tmp_path,
        FrontendRuntimeConfig(
            api_base_url="/api",
            environment="dev",
            locale_default="en",
        ),
    )

    app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")
    styles = (tmp_path / "assets" / "styles.css").read_text(encoding="utf-8")

    assert tmp_path / "assets" / "app.js" in manifest.files_written
    assert "window.__CHATBI_RUNTIME_CONFIG__" in app_js
    assert "show monthly revenue" in app_js
    assert "Revenue trend is ready." in app_js
    assert "trc_fixture_success" in app_js
    assert "#chatbi-root" in app_js
    assert ".app-shell" in styles
    assert ".answer-card" in styles


def test_build_static_cli_writes_index_html_from_arguments(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "frontend"
    stdout = StringIO()

    exit_code = main(
        [
            "--output-dir",
            str(output_dir),
            "--api-base-url",
            "/api",
            "--environment",
            "prod",
            "--locale-default",
            "en",
            "--title",
            "Governed ChatBI Console",
            "--app-script-src",
            "/assets/console.js",
            "--stylesheet-src",
            "/assets/console.css",
        ],
        env={},
        stdout=stdout,
    )

    html = (output_dir / "index.html").read_text(encoding="utf-8")

    assert exit_code == 0
    assert f"Wrote frontend index: {output_dir / 'index.html'}" in stdout.getvalue()
    assert "<title>Governed ChatBI Console</title>" in html
    assert '<script type="module" src="/assets/console.js"></script>' in html
    assert '<link rel="stylesheet" href="/assets/console.css">' in html
    assert '"api_base_url":"/api"' in html


def test_build_static_cli_reads_frontend_runtime_environment(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "frontend"

    exit_code = main(
        ["--output-dir", str(output_dir)],
        env={
            "API_BASE_URL": "https://chatbi.example.com/api",
            "FRONTEND_ENVIRONMENT": "staging",
            "FRONTEND_LOCALE_DEFAULT": "zh-CN",
        },
    )

    html = (output_dir / "index.html").read_text(encoding="utf-8")

    assert exit_code == 0
    assert '"api_base_url":"https://chatbi.example.com/api"' in html
    assert '"environment":"staging"' in html
    assert '"locale_default":"zh-CN"' in html


def test_build_static_cli_rejects_missing_runtime_config() -> None:
    stderr = StringIO()

    exit_code = main([], env={}, stderr=stderr)

    assert exit_code == 2
    assert "Frontend static build config error" in stderr.getvalue()
    assert "api_base_url" in stderr.getvalue()
