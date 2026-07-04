import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPO_ROOT / "frontend"


def read_frontend(path: str) -> str:
    return (FRONTEND_ROOT / path).read_text(encoding="utf-8")


def test_react_vite_frontend_has_buildable_project_contract() -> None:
    package = json.loads(read_frontend("package.json"))

    assert package["private"] is True
    assert package["type"] == "module"
    assert package["scripts"]["dev"] == "vite --host 0.0.0.0"
    assert package["scripts"]["build"] == "tsc -b && vite build"
    assert package["dependencies"]["react"].startswith("^18.")
    assert package["dependencies"]["react-dom"].startswith("^18.")
    assert "vite" in package["devDependencies"]
    assert "typescript" in package["devDependencies"]
    assert "@vitejs/plugin-react" in package["devDependencies"]
    assert "@types/node" in package["devDependencies"]


def test_react_vite_typescript_config_includes_browser_and_node_build_types() -> None:
    browser_tsconfig = json.loads(read_frontend("tsconfig.json"))
    node_tsconfig = json.loads(read_frontend("tsconfig.node.json"))
    vite_env = read_frontend("src/vite-env.d.ts")

    assert "ES2020" in browser_tsconfig["compilerOptions"]["lib"]
    assert browser_tsconfig["compilerOptions"]["moduleResolution"] == "Bundler"
    assert node_tsconfig["compilerOptions"]["target"] == "ES2020"
    assert "ES2020" in node_tsconfig["compilerOptions"]["lib"]
    assert node_tsconfig["compilerOptions"]["moduleResolution"] == "Bundler"
    assert "node" in node_tsconfig["compilerOptions"]["types"]
    assert "vite/client" in vite_env


def test_vite_frontend_routes_to_backend_api_contracts() -> None:
    app = read_frontend("src/App.tsx")
    vite = read_frontend("vite.config.ts")
    nginx = read_frontend("nginx.conf")

    for path in (
        "/healthz",
        "/api/v2/auth/login",
        "/api/v2/chat/query",
        "/api/v2/admin/observability/summary",
    ):
        assert path in app
    assert "VITE_API_BASE_URL" in app
    assert '"/api": "http://localhost:8000"' in vite
    assert '"/healthz": "http://localhost:8000"' in vite
    assert "proxy_pass http://backend:8000/api/" in nginx


def test_react_frontend_surfaces_governed_query_outputs() -> None:
    app = read_frontend("src/App.tsx")

    for expected in (
        "trace_id",
        "request_id",
        "answer_text",
        "answer",
        "table_result",
        "rows",
        "citations",
        "evidence_list",
        "agent_timeline",
        "agent_trace_id",
        "citation_anchor",
        "snippet",
        "warnings",
        "Idempotency-Key",
    ):
        assert expected in app


def test_react_frontend_maps_actual_v2_chat_response_shape() -> None:
    app = read_frontend("src/App.tsx")

    assert "function answerText(response: ChatResponse | undefined)" in app
    assert "response?.data?.answer_text ?? response?.data?.answer" in app
    assert "function tableRows(response: ChatResponse | undefined)" in app
    assert "response?.data?.table_result?.rows ?? response?.data?.rows ?? []" in app
    assert "function citationItems(response: ChatResponse | undefined)" in app
    assert "response?.data?.citations ?? response?.data?.evidence_list ?? []" in app
    assert "function agentTimeline(response: ChatResponse | undefined)" in app
    assert "response?.data?.agent_timeline ?? []" in app


def test_react_frontend_sends_valid_v2_request_id_for_chat_query() -> None:
    app = read_frontend("src/App.tsx")

    assert "function requestId()" in app
    assert "req_fe_" in app
    assert "const payloadBody = { ...chatPayload, request_id: requestId() }" in app
    assert "body: JSON.stringify(payloadBody)" in app


def test_react_frontend_normalizes_v2_session_id_contract() -> None:
    app = read_frontend("src/App.tsx")

    assert "function safeSessionId(value: string): string" in app
    assert "ses_demo_session" in app
    assert "session_id: safeSessionId(sessionId)" in app
    assert "/^ses_[A-Za-z0-9_-]{8,64}$/.test(value)" in app
    assert 'headers: { "Idempotency-Key":' in app


def test_react_frontend_uses_cockpit_layout_not_placeholder_sidebar() -> None:
    app = read_frontend("src/App.tsx")
    styles = read_frontend("src/styles.css")

    assert "Decision cockpit" in app
    assert "Sample questions" in app
    assert "side-panel" in app
    assert "evidence-card" in app
    assert "agent-timeline" in app
    assert "agent-status" in app
    assert ".main-grid" in styles
    assert ".inspector-card" in styles
    assert ".evidence-card" in styles
    assert ".agent-timeline" in styles
    assert ".agent-status.not_planned" in styles
    assert ".sidebar" not in styles


def test_react_frontend_does_not_embed_backend_only_secret_config() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((FRONTEND_ROOT / "src").rglob("*"))
        if path.is_file()
    )

    for forbidden in (
        "DATABASE_URL",
        "CHATBI_READONLY_DATABASE_URL",
        "POSTGRES_PASSWORD",
        "OPENAI_API_KEY",
        "REDIS_URL",
        "VECTOR_STORE_URL",
    ):
        assert forbidden not in combined


def test_react_frontend_renders_chart_spec_as_svg_chart() -> None:
    app = (FRONTEND_ROOT / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "chart_spec?: ChartSpec" in app
    assert "function ChartPanel" in app
    assert "<svg viewBox" in app
    assert "<path className=\"chart-line\"" in app
    assert "<ChartPanel spec={chart} rows={rows} />" in app
