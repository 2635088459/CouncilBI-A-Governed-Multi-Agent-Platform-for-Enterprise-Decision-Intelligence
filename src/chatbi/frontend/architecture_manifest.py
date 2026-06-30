"""Machine-readable architecture map for the v2 ChatBI frontend.

This module is deliberately descriptive. It does not render screens, fetch
data, or mutate state. Its job is to keep the frontend architecture easy to
audit against ``spec/version2/07-frontend-chatbi.spec.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chatbi.frontend.app_shell import FrontendRoute
from chatbi.frontend.render_model import RenderRegion


class FrontendLayer(StrEnum):
    RUNTIME_CONFIG = "runtime_config"
    API_CLIENT = "api_client"
    STATE = "state"
    COMPONENT_PROPS = "component_props"
    RENDER_MODEL = "render_model"
    STATIC_BUILD = "static_build"
    DEPLOYMENT = "deployment"


@dataclass(frozen=True, slots=True)
class FrontendPageContract:
    route: FrontendRoute
    title: str
    api_paths: tuple[str, ...]
    render_regions: tuple[RenderRegion, ...]
    state_module: str
    props_builder: str


@dataclass(frozen=True, slots=True)
class FrontendRequirementCoverage:
    requirement_id: str
    description: str
    layers: tuple[FrontendLayer, ...]
    tests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FrontendArchitectureManifest:
    spec_path: str
    pages: tuple[FrontendPageContract, ...]
    runtime_config_fields: tuple[str, ...]
    forbidden_runtime_config_fields: tuple[str, ...]
    packaged_commands: tuple[str, ...]
    static_entrypoints: tuple[str, ...]
    requirement_coverage: tuple[FrontendRequirementCoverage, ...]

    def page_for_route(self, route: FrontendRoute) -> FrontendPageContract:
        for page in self.pages:
            if page.route is route:
                return page
        raise ValueError(f"Unknown frontend route: {route.value}")

    def coverage_for_requirement(
        self,
        requirement_id: str,
    ) -> FrontendRequirementCoverage:
        for coverage in self.requirement_coverage:
            if coverage.requirement_id == requirement_id:
                return coverage
        raise ValueError(f"Unknown frontend requirement: {requirement_id}")


def build_frontend_architecture_manifest() -> FrontendArchitectureManifest:
    """Return the frontend contract map used by docs, tests, and reviewers."""

    return FrontendArchitectureManifest(
        spec_path="spec/version2/07-frontend-chatbi.spec.md",
        pages=(
            FrontendPageContract(
                route=FrontendRoute.CHAT,
                title="Chat Workspace",
                api_paths=("/api/v1/chat/query",),
                render_regions=(
                    RenderRegion.CHAT_INPUT,
                    RenderRegion.SEND_BUTTON,
                    RenderRegion.ANSWER_TEXT,
                    RenderRegion.TABLE,
                    RenderRegion.CHART,
                    RenderRegion.EVIDENCE_LIST,
                    RenderRegion.WARNING_LIST,
                    RenderRegion.TRACE_ID,
                    RenderRegion.ERROR_BOUNDARY,
                ),
                state_module="chatbi.frontend.chat_state",
                props_builder="build_chat_page_props",
            ),
            FrontendPageContract(
                route=FrontendRoute.HISTORY,
                title="History Panel",
                api_paths=("/api/v1/chat/history", "/api/v1/query/{trace_id}"),
                render_regions=(RenderRegion.HISTORY_LIST,),
                state_module="chatbi.frontend.history_state",
                props_builder="build_history_page_props",
            ),
            FrontendPageContract(
                route=FrontendRoute.CATALOG,
                title="Metric Catalog",
                api_paths=("/api/v1/metrics/catalog",),
                render_regions=(
                    RenderRegion.CATALOG_SEARCH,
                    RenderRegion.CATALOG_LIST,
                    RenderRegion.CATALOG_DETAIL,
                ),
                state_module="chatbi.frontend.catalog_state",
                props_builder="build_catalog_page_props",
            ),
            FrontendPageContract(
                route=FrontendRoute.TASK_STATUS,
                title="Task Status",
                api_paths=("/api/v1/chat/tasks/{task_id}",),
                render_regions=(RenderRegion.TASK_STATUS_CARD,),
                state_module="chatbi.frontend.task_status_page_state",
                props_builder="build_task_status_page_props",
            ),
            FrontendPageContract(
                route=FrontendRoute.EVALUATION,
                title="Evaluation",
                api_paths=("/api/v1/evals/run",),
                render_regions=(RenderRegion.EVALUATION_REPORT,),
                state_module="chatbi.frontend.evaluation_state",
                props_builder="build_evaluation_page_props",
            ),
        ),
        runtime_config_fields=("api_base_url", "environment", "locale_default"),
        forbidden_runtime_config_fields=(
            "database_url",
            "redis_url",
            "vector_store_url",
            "agent_url",
        ),
        packaged_commands=("chatbi-build-frontend",),
        static_entrypoints=("index.html", "/assets/app.js", "/assets/styles.css"),
        requirement_coverage=(
            FrontendRequirementCoverage(
                requirement_id="FR-07-001",
                description="Chat workspace submits questions through the Backend API.",
                layers=(FrontendLayer.API_CLIENT, FrontendLayer.STATE),
                tests=("tests/test_frontend_api_client.py", "tests/test_frontend_backend_flow.py"),
            ),
            FrontendRequirementCoverage(
                requirement_id="FR-07-002",
                description="Chat workspace renders answer, table, chart, evidence, warnings, trace.",
                layers=(FrontendLayer.COMPONENT_PROPS, FrontendLayer.RENDER_MODEL),
                tests=("tests/test_frontend_render_model.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="FR-07-003",
                description="History panel fetches and renders previous query records.",
                layers=(FrontendLayer.API_CLIENT, FrontendLayer.STATE, FrontendLayer.RENDER_MODEL),
                tests=("tests/test_frontend_history_component_props.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="FR-07-004",
                description="Metric catalog fetches and renders governed metric definitions.",
                layers=(FrontendLayer.API_CLIENT, FrontendLayer.STATE, FrontendLayer.RENDER_MODEL),
                tests=("tests/test_frontend_catalog_component_props.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="FR-07-005",
                description="Task status page renders queued, running, partial, failed, completed.",
                layers=(FrontendLayer.STATE, FrontendLayer.COMPONENT_PROPS),
                tests=("tests/test_frontend_task_status_state.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="FR-07-006",
                description="Error boundary renders user-actionable API error states.",
                layers=(FrontendLayer.STATE, FrontendLayer.COMPONENT_PROPS),
                tests=("tests/test_frontend_component_props.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="NFR-07-001",
                description="Fixture-backed first meaningful render stays within local budget.",
                layers=(FrontendLayer.RENDER_MODEL,),
                tests=("tests/test_frontend_performance.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="NFR-07-002",
                description="Submit-to-loading transition stays within local budget.",
                layers=(FrontendLayer.STATE,),
                tests=("tests/test_frontend_performance.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="NFR-07-003",
                description="Frontend query logs include request, session, and event fields.",
                layers=(FrontendLayer.API_CLIENT,),
                tests=("tests/test_frontend_observability.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="NFR-07-004",
                description="Frontend API and UI state models type-check cleanly.",
                layers=(FrontendLayer.API_CLIENT, FrontendLayer.STATE),
                tests=("tests/test_frontend_ui_answer_state.py",),
            ),
            FrontendRequirementCoverage(
                requirement_id="VR-07-005",
                description="Browser runtime config excludes backend infrastructure URLs.",
                layers=(FrontendLayer.RUNTIME_CONFIG, FrontendLayer.STATIC_BUILD),
                tests=("tests/test_frontend_runtime_config.py",),
            ),
        ),
    )
