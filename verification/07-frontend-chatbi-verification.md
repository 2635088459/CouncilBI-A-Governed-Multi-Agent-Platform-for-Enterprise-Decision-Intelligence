# Verification: 07 Frontend ChatBI v2

This document records the current machine-verifiable status for
`spec/version2/07-frontend-chatbi.spec.md`.

## Scope

Verified frontend slice:

```text
Browser runtime config
  -> browser-safe API base URL, environment, and locale
  -> forbidden backend infrastructure URLs rejected

Backend API client
  -> v2 ApiEnvelope parsing
  -> request/session/trace headers
  -> typed fixtures and HTTP transport boundary

Frontend state
  -> chat submit and loading transition
  -> answer state: idle, submitting, running, partial, failed, completed
  -> history, catalog, task status, and evaluation page stores

Presentation contract
  -> framework-neutral component props
  -> app shell navigation
  -> render regions for tests before a browser framework is attached

Static deployment
  -> index.html bootstrap
  -> runtime config script injection
  -> app.js and styles.css browser prototype assets
  -> chatbi-build-frontend packaged command
  -> Docker Compose and Kubernetes runtime env wiring
```

Covered frontend surface:

| Surface | Status |
|---|---|
| Chat workspace | Implemented and covered |
| History panel | Implemented and covered |
| Metric catalog | Implemented and covered |
| Task status page | Implemented and covered |
| Evaluation page | Implemented and covered |
| Error boundary | Implemented and covered |
| Runtime config | Implemented with forbidden backend URL checks |
| Static HTML bootstrap | Implemented and covered |
| Browser UI prototype assets | Implemented and covered |
| Static frontend build CLI | Implemented and packaged as `chatbi-build-frontend` |
| Docker Compose frontend runtime env | Implemented and covered |
| Kubernetes frontend runtime env and ingress | Implemented and covered |

## Page Architecture

| Route | Page | Backend API Paths | Render Regions |
|---|---|---|---|
| `chat` | Chat Workspace | `POST /api/v1/chat/query` | input, send button, answer, table, chart, evidence, warnings, trace id, error boundary |
| `history` | History Panel | `GET /api/v1/chat/history`, `GET /api/v1/query/{trace_id}` | history list |
| `catalog` | Metric Catalog | `GET /api/v1/metrics/catalog` | search, list, detail |
| `task_status` | Task Status | `GET /api/v1/chat/tasks/{task_id}` | task status card |
| `evaluation` | Evaluation | `POST /api/v1/evals/run` | evaluation report |

## Covered Requirements

| Requirement | Verification |
|---|---|
| `VR-07-001` | API client methods use Backend API paths under the configured API base URL through the transport boundary. See `tests/test_frontend_api_client.py` and `tests/test_frontend_http_transport.py`. |
| `VR-07-002` | API responses are normalized through `parse_api_envelope`. See `tests/test_frontend_api_client.py`. |
| `VR-07-003` | Trace id display and copy props are built when a trace id is present. See `tests/test_frontend_component_props.py` and `tests/test_frontend_render_model.py`. |
| `VR-07-004` | `AGENT_PARTIAL_FAILURE` becomes a warning/partial state while keeping available data visible. See `tests/test_frontend_ui_answer_state.py` and `tests/test_frontend_render_model.py`. |
| `VR-07-005` | Runtime config rejects database, Redis, vector store, and agent URLs. See `tests/test_frontend_runtime_config.py`. |
| `FR-07-001` | Chat submit calls `/api/v1/chat/query` with request/session/trace headers. |
| `FR-07-002` | Successful answer fixtures render answer text, table, chart, evidence, warnings, and trace id. |
| `FR-07-003` | History panel fetches and renders records from `/api/v1/chat/history`. |
| `FR-07-004` | Metric catalog fetches and renders records from `/api/v1/metrics/catalog`. |
| `FR-07-005` | Task status maps queued, running, partial, failed, and completed states to UI state. |
| `FR-07-006` | Error boundary renders validation, SQL guardrail denial, and internal error states with user-facing messages. |
| `NFR-07-001` | Fixture-backed first meaningful render performance is covered by `tests/test_frontend_performance.py`. |
| `NFR-07-002` | Submit-to-loading transition performance is covered by `tests/test_frontend_performance.py`. |
| `NFR-07-003` | Frontend query logs include request id, session id, trace id, user id, and event. |
| `NFR-07-004` | Focused pyright checks for frontend source files return 0 errors. |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-07-001` | The successful fixture path submits "show monthly revenue" once to `/api/v1/chat/query` with request and session headers. |
| `AC-07-002` | Successful fixture render model includes answer text, table, chart, evidence list, warning list, and trace id. |
| `AC-07-003` | Partial failure fixture renders partial warning state and keeps table/chart data visible. |
| `AC-07-004` | SQL guardrail denial fixture renders error boundary with `SQL_GUARDRAIL_DENIED` and trace id. |
| `AC-07-005` | Runtime config and static bootstrap tests fail if backend-only infrastructure URLs leak into frontend config. |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-07-001` | Pyright validates frontend runtime config, API client, UI state, architecture manifest, and report modules. |
| `TC-07-002` | `tests/test_frontend_api_client.py` and `tests/test_frontend_backend_flow.py` verify submit payload and headers. |
| `TC-07-003` | `tests/test_frontend_render_model.py` verifies successful answer fixture render regions. |
| `TC-07-004` | `tests/test_frontend_render_model.py` and `tests/test_frontend_ui_answer_state.py` verify partial failure warning behavior. |
| `TC-07-005` | `tests/test_frontend_render_model.py` verifies SQL guardrail denial rendering. |
| `TC-07-006` | `tests/test_frontend_runtime_config.py` verifies forbidden URL rejection. |
| `TC-07-007` | `tests/test_frontend_performance.py` verifies local render and loading transition budgets. |
| `TC-07-008` | `src/chatbi/frontend/architecture_report.py` renders a human-readable architecture summary from the machine-readable manifest. |

## Design Notes

The frontend is intentionally framework-neutral at this stage:

1. `src/chatbi/frontend/api_client.py` is the only frontend-facing Backend API client.
2. `src/chatbi/frontend/*_state.py` modules own page state transitions.
3. `src/chatbi/frontend/component_props.py` converts state into UI-ready props.
4. `src/chatbi/frontend/render_model.py` flattens props into testable render regions.
5. `src/chatbi/frontend/runtime_config.py` keeps browser runtime configuration safe.
6. `src/chatbi/frontend/static_bootstrap.py` builds the HTML mount document.
7. `src/chatbi/frontend/static_assets/app.js` and `styles.css` provide a minimal browser prototype.
8. `src/chatbi/frontend/build_static.py` writes deployable static assets and provides the CLI.
9. `src/chatbi/frontend/architecture_manifest.py` records the spec-to-code architecture map.
10. `src/chatbi/frontend/architecture_report.py` renders that map as Markdown for review.

In plain terms: the API client talks to the backend, state stores remember what
happened, props describe what the screen needs, render models make it testable,
and the static build layer turns the frontend into deployable files that can be opened in a browser.

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused Frontend v2 suite:

```bash
.venv/bin/python -m pytest \
  tests/test_frontend_architecture_report.py \
  tests/test_frontend_architecture_manifest.py \
  tests/test_frontend_cli_packaging.py \
  tests/test_frontend_build_static.py \
  tests/test_frontend_runtime_config.py \
  tests/test_frontend_static_bootstrap.py \
  tests/test_frontend_performance.py \
  tests/test_frontend_render_model.py \
  tests/test_frontend_fixture_transport.py \
  tests/test_frontend_api_fixtures.py \
  tests/test_frontend_observability.py \
  tests/test_frontend_api_client.py \
  tests/test_frontend_http_transport.py \
  tests/test_frontend_i18n.py \
  tests/test_frontend_app_shell.py \
  tests/test_frontend_app_shell_props.py \
  tests/test_frontend_app_screen_model.py \
  tests/test_frontend_backend_flow.py \
  tests/test_frontend_chat_state.py \
  tests/test_frontend_component_props.py \
  tests/test_frontend_catalog_component_props.py \
  tests/test_frontend_history_component_props.py \
  tests/test_frontend_evaluation_component_props.py \
  tests/test_frontend_task_status_component_props.py \
  tests/test_frontend_task_status_page_state.py \
  tests/test_frontend_task_status_state.py \
  tests/test_frontend_ui_answer_state.py \
  tests/test_frontend_view_models.py \
  tests/test_frontend_catalog_state.py \
  tests/test_frontend_history_state.py \
  tests/test_frontend_evaluation_state.py \
  tests/test_docker_compose_architecture.py \
  tests/test_k8s_runtime_architecture.py
```

Result:

```text
156 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient.
```

This warning comes from the third-party FastAPI/TestClient stack and does not
indicate a failing frontend test.

Focused static checks:

```bash
.venv/bin/pyright src/chatbi/frontend/architecture_report.py src/chatbi/frontend/architecture_manifest.py tests/test_frontend_architecture_report.py
.venv/bin/pyright src/chatbi/frontend/build_static.py tests/test_frontend_build_static.py
.venv/bin/pyright src/chatbi/frontend/static_bootstrap.py src/chatbi/frontend/runtime_config.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

## Browser Prototype Verification

Static prototype build command:

```bash
.venv/bin/python -m chatbi.frontend.build_static \
  --output-dir /private/tmp/chatbi-frontend-spec7 \
  --api-base-url /api \
  --environment dev \
  --locale-default en
```

Generated files:

```text
/private/tmp/chatbi-frontend-spec7/index.html
/private/tmp/chatbi-frontend-spec7/assets/app.js
/private/tmp/chatbi-frontend-spec7/assets/styles.css
```

The generated `index.html` includes:

```html
<main id="chatbi-root" data-app="chatbi"></main>
<script>window.__CHATBI_RUNTIME_CONFIG__={"api_base_url":"/api","environment":"dev","locale_default":"en"};</script>
<script type="module" src="/assets/app.js"></script>
```

Visible prototype regions represented by `app.js` and `styles.css`:

| Region | Evidence |
|---|---|
| Navigation | `InsightOps AI`, Chat, History, Catalog, Task, Evaluation |
| Runtime config | API base URL, environment, and locale badges |
| Chat input | `show monthly revenue` fixture question |
| Submit button | Local click handler re-renders the answer region |
| Answer | `Revenue trend is ready.` |
| Table | Month and revenue rows |
| Chart | Local bar chart placeholder |
| Evidence | Semantic metric and trace-linked result entries |
| Warning | Fixture mode warning |
| Trace id | `trc_fixture_success` |

This closes the spec7 browser loop at a minimal prototype level:

```text
spec -> code -> tests -> static build -> browser prototype assets -> verification document
```

## Remaining Work

- Attach a real browser framework bundle to `#chatbi-root`.
- Add browser-level accessibility and visual regression checks once the actual UI implementation exists.
- Add CI artifact generation for `verification/07-frontend-chatbi-verification.md` if the team wants the report regenerated automatically.
