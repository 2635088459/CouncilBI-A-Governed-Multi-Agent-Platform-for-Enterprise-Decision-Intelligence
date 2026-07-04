# Final Risk Register

| Risk | Status | Mitigation / Next Step |
|---|---|---|
| Real provider costs and rate limits | Managed | Baseline tests use mock providers; real OpenAI smoke test is opt-in with `OPENAI_API_KEY`. |
| Cloud credentials in repository | Managed | Deployment artifacts use secret references/placeholders and `tests/test_cloud_secret_scan.py`. |
| No live staging cluster in local verification | Open | CI workflow supports staging deploy when `STAGING_KUBE_CONFIG_B64` and staging vars/secrets are configured. |
| Production vector database choice | Open | Current final-version RAG supports deterministic local vector store and retry wrappers; production can replace the `VectorStore` protocol. |
| External APM backend | Open | Internal traces, logs, metrics, and admin observability exist; future work can add OpenTelemetry exporters. |
| Formal compliance certification | Out of scope | Not required for course/final submission; would need separate SOC 2/ISO program. |
| Load testing beyond local reports | Partial | Local mock load reports exist; staging load testing should be run after cloud environment is provisioned. |
