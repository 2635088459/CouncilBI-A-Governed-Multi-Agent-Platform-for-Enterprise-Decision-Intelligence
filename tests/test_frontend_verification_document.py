from pathlib import Path


def test_frontend_verification_document_records_spec_and_latest_checks() -> None:
    document = Path("verification/07-frontend-chatbi-verification.md").read_text(
        encoding="utf-8"
    )

    assert "spec/version2/07-frontend-chatbi.spec.md" in document
    assert "| `chat` | Chat Workspace | `POST /api/v1/chat/query` |" in document
    assert "`chatbi-build-frontend`" in document
    assert "app.js and styles.css browser prototype assets" in document
    assert "## Browser Prototype Verification" in document
    assert "/private/tmp/chatbi-frontend-spec7/index.html" in document
    assert "/private/tmp/chatbi-frontend-spec7/assets/app.js" in document
    assert "/private/tmp/chatbi-frontend-spec7/assets/styles.css" in document
    assert "Visible prototype regions represented by `app.js` and `styles.css`" in document
    assert "Revenue trend is ready." in document
    assert "trc_fixture_success" in document
    assert "spec -> code -> tests -> static build -> browser prototype assets" in document
    assert "database, Redis, vector store, and agent URLs" in document
    assert "156 passed, 1 warning" in document
    assert "0 errors, 0 warnings, 0 informations" in document
