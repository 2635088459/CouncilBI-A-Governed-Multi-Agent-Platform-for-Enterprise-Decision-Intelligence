"""Render the frontend architecture manifest as Markdown.

The manifest is useful for tests and tooling. This report turns the same data
into a compact human-readable guide for implementation reviews and study notes.
"""

from __future__ import annotations

from chatbi.frontend.architecture_manifest import (
    FrontendArchitectureManifest,
    build_frontend_architecture_manifest,
)


def render_frontend_architecture_report(
    manifest: FrontendArchitectureManifest | None = None,
) -> str:
    manifest = manifest or build_frontend_architecture_manifest()
    lines = [
        "# Frontend ChatBI Architecture Report",
        "",
        f"Spec: `{manifest.spec_path}`",
        "",
        "## Pages",
        "",
        "| Route | Page | API Paths | Render Regions | State Module | Props Builder |",
        "|---|---|---|---|---|---|",
    ]
    for page in manifest.pages:
        lines.append(
            "| "
            f"`{page.route.value}` | "
            f"{page.title} | "
            f"{_join_code(page.api_paths)} | "
            f"{_join_code(tuple(region.value for region in page.render_regions))} | "
            f"`{page.state_module}` | "
            f"`{page.props_builder}` |"
        )

    lines.extend(
        [
            "",
            "## Runtime Config",
            "",
            f"Public fields: {_join_code(manifest.runtime_config_fields)}",
            "",
            f"Forbidden fields: {_join_code(manifest.forbidden_runtime_config_fields)}",
            "",
            "## Static Build",
            "",
            f"Commands: {_join_code(manifest.packaged_commands)}",
            "",
            f"Entrypoints: {_join_code(manifest.static_entrypoints)}",
            "",
            "## Requirement Coverage",
            "",
            "| Requirement | Layers | Tests | Description |",
            "|---|---|---|---|",
        ]
    )
    for coverage in manifest.requirement_coverage:
        lines.append(
            "| "
            f"`{coverage.requirement_id}` | "
            f"{_join_code(tuple(layer.value for layer in coverage.layers))} | "
            f"{_join_code(coverage.tests)} | "
            f"{coverage.description} |"
        )

    lines.append("")
    return "\n".join(lines)


def _join_code(values: tuple[str, ...]) -> str:
    return ", ".join(f"`{value}`" for value in values)
