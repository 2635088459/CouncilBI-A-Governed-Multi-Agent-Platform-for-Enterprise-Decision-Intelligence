# Demo Report Artifacts

This directory contains the GitHub-visible demo report package for InsightOps AI.

| Artifact | Link |
|---|---|
| Demo report deck | [chatbi-demo-report.pptx](chatbi-demo-report.pptx) |
| Evaluation summary | [report-evaluation-summary.md](report-evaluation-summary.md) |
| Token savings report | [token-savings-report.md](token-savings-report.md) |
| Stable sustained benchmark | [gke-sustained-stable-benchmark.md](gke-sustained-stable-benchmark.md) |
| Overload/rate-limit stress benchmark | [gke-sustained-rate-limit-stress.md](gke-sustained-rate-limit-stress.md) |
| Extended correctness benchmark | [gke-extended-correctness.md](gke-extended-correctness.md) |
| Pod recovery drill | [gke-pod-recovery-drill.md](gke-pod-recovery-drill.md) |
| Resource utilization after stable load | [gke-resource-utilization-after-stable-load.md](gke-resource-utilization-after-stable-load.md) |

Notes:

- The GKE URL used in these reports is a staging LoadBalancer address and may change if the cluster or service is recreated.
- Cloud measurements use the mock LLM provider for reproducible staging tests. Exact OpenAI billing/token numbers require running the same cases with the real OpenAI provider and reading provider `usage` fields.
