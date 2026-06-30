from chatbi.frontend.runtime_config import (
    FrontendRuntimeConfig,
    parse_frontend_runtime_config,
)
from chatbi.frontend.static_bootstrap import build_static_index_html


def test_build_static_index_html_injects_runtime_config_and_mount_point() -> None:
    html = build_static_index_html(
        FrontendRuntimeConfig(
            api_base_url="/api",
            environment="prod",
            locale_default="en",
        )
    )

    assert '<main id="chatbi-root" data-app="chatbi"></main>' in html
    assert (
        'window.__CHATBI_RUNTIME_CONFIG__={"api_base_url":"/api",'
        '"environment":"prod","locale_default":"en"};'
    ) in html
    assert '<link rel="stylesheet" href="/assets/styles.css">' in html
    assert '<script type="module" src="/assets/app.js"></script>' in html
    assert "DATABASE_URL" not in html
    assert "REDIS_URL" not in html
    assert "VECTOR_STORE_URL" not in html


def test_build_static_index_html_escapes_title_and_script_src() -> None:
    html = build_static_index_html(
        FrontendRuntimeConfig(
            api_base_url="/api",
            environment="dev",
            locale_default="zh-CN",
        ),
        title='ChatBI "Admin"',
        app_script_src='/assets/app.js?build="local"',
        stylesheet_src='/assets/styles.css?build="local"',
    )

    assert "<title>ChatBI &quot;Admin&quot;</title>" in html
    assert 'src="/assets/app.js?build=&quot;local&quot;"' in html
    assert 'href="/assets/styles.css?build=&quot;local&quot;"' in html


def test_runtime_config_script_cannot_close_script_tag() -> None:
    config = parse_frontend_runtime_config(
        {
            "api_base_url": "/api</script><script>alert(1)</script>",
            "environment": "dev",
            "locale_default": "en",
        }
    )

    html = build_static_index_html(config)

    runtime_script_line = next(
        line for line in html.splitlines() if "__CHATBI_RUNTIME_CONFIG__" in line
    )
    assert "</script><script>" not in runtime_script_line
    assert "<\\/script>" in runtime_script_line
