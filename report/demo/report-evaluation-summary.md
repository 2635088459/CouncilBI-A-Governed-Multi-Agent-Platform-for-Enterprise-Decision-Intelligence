# Report Evaluation Summary

## Scope

- Environment: GKE Autopilot staging, public HTTP endpoint
- Base URL: http://136.69.23.39
- LLM provider: mock provider for reproducible cloud staging tests
- Secret handling: OpenAI API key is injected into backend/worker from Kubernetes Secret, not committed in YAML

## Main Results

| Area | Metric | Result | Evidence File |
| --- | --- | ---: | --- |
| Stable sustained load | Duration | 600.0 seconds | gke-sustained-stable-benchmark.md |
| Stable sustained load | Requests | 480 | gke-sustained-stable-benchmark.md |
| Stable sustained load | Success rate | 100% | gke-sustained-stable-benchmark.md |
| Stable sustained load | Throughput | 0.8 RPS | gke-sustained-stable-benchmark.md |
| Stable sustained load | P50 latency | 96.033 ms | gke-sustained-stable-benchmark.md |
| Stable sustained load | P95 latency | 176.69 ms | gke-sustained-stable-benchmark.md |
| Stable sustained load | P99 latency | 262.5507 ms | gke-sustained-stable-benchmark.md |
| Stable sustained load | Status codes | 480 HTTP 200 | gke-sustained-stable-benchmark.md |
| Burst load | Requests / concurrency | 50 / 10 | gke-staging-metrics.md |
| Burst load | Success rate | 100% | gke-staging-metrics.md |
| Burst load | Throughput | 76.4678 RPS | gke-staging-metrics.md |
| Burst load | P95 latency | 183.4015 ms | gke-staging-metrics.md |
| Overload protection | Requests / target rate | 12000 / 20 RPS | gke-sustained-rate-limit-stress.md |
| Overload protection | Accepted requests | 1200 HTTP 200 | gke-sustained-rate-limit-stress.md |
| Overload protection | Rate-limited requests | 10799 HTTP 429 | gke-sustained-rate-limit-stress.md |
| Overload protection | Server-side transient failure | 1 HTTP 502 | gke-sustained-rate-limit-stress.md |
| Correctness | Expanded golden cases | 12/12 passed | gke-extended-correctness.md |
| Correctness | Correctness rate | 100% | gke-extended-correctness.md |
| Multi-agent | Avg tool/agent calls per success | 5.0 | gke-sustained-stable-benchmark.md |
| Multi-agent | Agent step success rate | 100% | gke-sustained-stable-benchmark.md |
| Multi-agent | Collaboration success rate | 100% | gke-sustained-stable-benchmark.md |
| Guardrail | Dangerous SQL detection rate | 100% | gke-staging-metrics.md |
| Guardrail | Benign SQL allow rate | 100% | gke-staging-metrics.md |
| Guardrail | Guardrail P95 latency | 168.5455 ms | gke-staging-metrics.md |
| Recovery | Backend pod recovery time | 21 seconds | gke-pod-recovery-drill.md |
| Recovery | Post-recovery chat status | HTTP 200 | gke-pod-recovery-drill.md |
| Resource usage | Backend pods after stable load | 6m/115Mi and 7m/120Mi | gke-resource-utilization-after-stable-load.md |
| Resource usage | Node after stable load | 2% CPU, 5% memory | gke-resource-utilization-after-stable-load.md |
| Optimization | Prior baseline P95 | 256.9212 ms | gke-repeated-concurrency-summary.md |
| Optimization | Best repeated average P95 | 171.5268 ms | gke-repeated-concurrency-summary.md |
| Optimization | P95 improvement | 33.24% | gke-repeated-concurrency-summary.md |
| Token efficiency | Optimized total tokens | 6508 | token-savings-report.md |
| Token efficiency | Naive full-context total tokens | 326696 | token-savings-report.md |
| Token efficiency | Tokens saved | 320188 | token-savings-report.md |
| Token efficiency | Token reduction rate | 98.01% | token-savings-report.md |
| Token efficiency | Avg optimized tokens/question | 1084.6667 | token-savings-report.md |
| Token efficiency | Avg naive tokens/question | 54449.3333 | token-savings-report.md |
| Local resilience | Retry recovered transient failure | True | report-metrics.md |
| Local resilience | Circuit breaker half-open after cooldown | True | report-metrics.md |
| Local resilience | Timeout denial | True | report-metrics.md |
| Local hallucination control | RAG faithfulness score | 100% | report-metrics.md |
| Local hallucination control | Unsupported claim rate | 10% | report-metrics.md |

## Recommended Report Interpretation

Use the 0.8 RPS sustained benchmark as the steady-state reliability result. It shows the deployed system handled a full 10-minute window with 480/480 successful requests and no 429/5xx responses.

Use the 20 RPS sustained benchmark as the overload governance result. It intentionally exceeded the configured rate-limit policy and produced 10799 HTTP 429 responses, proving that the platform fails closed under excessive traffic instead of allowing unbounded model/tool execution.

Use the 50-request burst benchmark as the short-window throughput result. It reached 76.4678 RPS with 100% success and P95 latency of 183.4015 ms.

Use the token-efficiency benchmark to explain why governed SQL and RAG reduce model cost. The optimized path sends schema, bounded SQL rows, and top evidence snippets, while the naive baseline sends multi-year database rows and broad enterprise document context. Across six complex executive-analysis questions, the optimized path reduced estimated token usage by 98.01%.

Because staging is configured with the mock LLM provider, correctness and latency numbers are reproducible cloud engineering measurements, not real OpenAI quality or token-latency measurements. A final optional production-quality eval would switch only a small golden set to the real OpenAI provider and report human-graded answer quality separately.
