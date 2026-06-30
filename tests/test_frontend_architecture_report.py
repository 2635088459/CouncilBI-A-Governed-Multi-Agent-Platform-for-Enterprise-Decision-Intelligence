from chatbi.frontend.architecture_report import render_frontend_architecture_report


def test_frontend_architecture_report_renders_pages_runtime_and_static_build() -> None:
    report = render_frontend_architecture_report()

    assert report.startswith("# Frontend ChatBI Architecture Report\n")
    assert "Spec: `spec/version2/07-frontend-chatbi.spec.md`" in report
    assert "| `chat` | Chat Workspace | `/api/v1/chat/query` |" in report
    assert "`answer_text`" in report
    assert "Public fields: `api_base_url`, `environment`, `locale_default`" in report
    assert (
        "Forbidden fields: `database_url`, `redis_url`, `vector_store_url`, `agent_url`"
        in report
    )
    assert "Commands: `chatbi-build-frontend`" in report
    assert "Entrypoints: `index.html`, `/assets/app.js`, `/assets/styles.css`" in report


def test_frontend_architecture_report_renders_requirement_coverage() -> None:
    report = render_frontend_architecture_report()

    assert "| `FR-07-001` | `api_client`, `state` |" in report
    assert "`tests/test_frontend_api_client.py`" in report
    assert "Chat workspace submits questions through the Backend API." in report
    assert "| `VR-07-005` | `runtime_config`, `static_build` |" in report
