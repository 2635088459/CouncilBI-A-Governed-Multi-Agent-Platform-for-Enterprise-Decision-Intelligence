from chatbi.frontend.app_shell import FrontendRoute
from chatbi.frontend.architecture_manifest import (
    FrontendLayer,
    build_frontend_architecture_manifest,
)
from chatbi.frontend.render_model import RenderRegion


def test_frontend_architecture_manifest_lists_all_app_routes() -> None:
    manifest = build_frontend_architecture_manifest()

    assert tuple(page.route for page in manifest.pages) == tuple(FrontendRoute)


def test_frontend_architecture_manifest_maps_pages_to_api_paths_and_regions() -> None:
    manifest = build_frontend_architecture_manifest()

    chat = manifest.page_for_route(FrontendRoute.CHAT)
    history = manifest.page_for_route(FrontendRoute.HISTORY)
    catalog = manifest.page_for_route(FrontendRoute.CATALOG)
    task_status = manifest.page_for_route(FrontendRoute.TASK_STATUS)

    assert chat.api_paths == ("/api/v1/chat/query",)
    assert RenderRegion.TRACE_ID in chat.render_regions
    assert RenderRegion.ERROR_BOUNDARY in chat.render_regions
    assert history.api_paths == ("/api/v1/chat/history", "/api/v1/query/{trace_id}")
    assert catalog.render_regions == (
        RenderRegion.CATALOG_SEARCH,
        RenderRegion.CATALOG_LIST,
        RenderRegion.CATALOG_DETAIL,
    )
    assert task_status.api_paths == ("/api/v1/chat/tasks/{task_id}",)


def test_frontend_architecture_manifest_records_runtime_and_static_contracts() -> None:
    manifest = build_frontend_architecture_manifest()

    assert manifest.runtime_config_fields == (
        "api_base_url",
        "environment",
        "locale_default",
    )
    assert manifest.forbidden_runtime_config_fields == (
        "database_url",
        "redis_url",
        "vector_store_url",
        "agent_url",
    )
    assert manifest.packaged_commands == ("chatbi-build-frontend",)
    assert manifest.static_entrypoints == ("index.html", "/assets/app.js", "/assets/styles.css")


def test_frontend_architecture_manifest_covers_spec_07_requirements() -> None:
    manifest = build_frontend_architecture_manifest()

    requirement_ids = {coverage.requirement_id for coverage in manifest.requirement_coverage}

    assert {
        "FR-07-001",
        "FR-07-002",
        "FR-07-003",
        "FR-07-004",
        "FR-07-005",
        "FR-07-006",
        "NFR-07-001",
        "NFR-07-002",
        "NFR-07-003",
        "NFR-07-004",
        "VR-07-005",
    }.issubset(requirement_ids)


def test_frontend_architecture_manifest_can_lookup_requirement_coverage() -> None:
    manifest = build_frontend_architecture_manifest()

    coverage = manifest.coverage_for_requirement("FR-07-001")

    assert FrontendLayer.API_CLIENT in coverage.layers
    assert "tests/test_frontend_api_client.py" in coverage.tests
