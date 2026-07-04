# Final Demo Script

Target duration after environment setup: 15 minutes or less.

## 1. Sign In

1. Start Docker Compose or run the backend with the React + Vite frontend.
2. Create or use a seeded user.
3. Open `http://localhost:8080` for Docker Compose or the Vite dev URL.
4. Use the login panel or call `/api/v2/auth/login`.
5. Confirm the access token works with `/api/v2/me`.

Pass criteria: user id, organization id, roles, and permissions are returned.

## 2. User Chat Flow

1. Submit a business question such as `Which support ticket area needs attention?` from the React UI, or call `/api/v2/chat/query`.
2. Confirm the response includes `trace_id`, answer text, support-ticket table rows, evidence, SQL text or safe denial, and confidence.
3. Open the Trace tab or the trace endpoint for the returned trace id.
4. Ask `Which month had the highest revenue in 2012?` and confirm the answer is `2012-12` with seeded monthly rows.

Pass criteria: answer is traceable and does not expose secrets.

## 3. RAG Citation Flow

1. Index a short document with `/api/v2/documents/index`.
2. Ask an explanation question such as `Explain why revenue changed`.
3. Confirm citations/evidence are present when matching evidence exists.

Pass criteria: answer includes citation metadata and tenant-scoped evidence. SQL-only seeded demos should include data-provenance evidence when document RAG is not part of the route.

## 4. Admin Observability Flow

1. Sign in as an admin user.
2. Open the Admin tab or call `/api/v2/admin/observability/summary`.
3. Inspect system health, LLM health, SQL safety, RAG health, eval summary, release gate, and audit summary.

Pass criteria: admin-only data is visible to admin and denied to non-admin.

## 5. Release Gate Flow

1. Run passing release-gate tests.
2. Run the failing fixture test that proves the gate blocks a bad release.
3. Inspect the release gate output in the admin observability summary.

Pass criteria: passing fixture allows release, failing fixture returns a blocker.
