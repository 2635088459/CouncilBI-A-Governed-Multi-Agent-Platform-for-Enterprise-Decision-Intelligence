"""Static HTML bootstrap document for the ChatBI frontend.

This module is intentionally framework-neutral. A future React/Vue/Svelte
bundle can mount into ``#chatbi-root`` while the runtime API URL remains
injected at container startup.
"""

from __future__ import annotations

from html import escape

from chatbi.frontend.runtime_config import (
    FrontendRuntimeConfig,
    frontend_runtime_config_script,
)


def build_static_index_html(
    config: FrontendRuntimeConfig,
    *,
    title: str = "Governed ChatBI",
    app_script_src: str = "/assets/app.js",
    stylesheet_src: str = "/assets/styles.css",
) -> str:
    safe_title = escape(title, quote=True)
    safe_script_src = escape(app_script_src, quote=True)
    safe_stylesheet_src = escape(stylesheet_src, quote=True)
    runtime_script = frontend_runtime_config_script(config)
    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="en">',
            "  <head>",
            '    <meta charset="utf-8">',
            '    <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"    <title>{safe_title}</title>",
            f'    <link rel="stylesheet" href="{safe_stylesheet_src}">',
            "  </head>",
            "  <body>",
            '    <main id="chatbi-root" data-app="chatbi"></main>',
            f"    <script>{runtime_script}</script>",
            f'    <script type="module" src="{safe_script_src}"></script>',
            "  </body>",
            "</html>",
            "",
        )
    )
