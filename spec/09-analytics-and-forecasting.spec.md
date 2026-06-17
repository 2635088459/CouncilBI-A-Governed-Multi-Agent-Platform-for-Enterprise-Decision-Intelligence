# Spec: Analytics and Forecasting

## 1. Purpose
Define the anomaly detection and forecasting behavior that produces explainable KPI intelligence.

## 2. Scope
In scope:
- Time-series preprocessing and data quality checks
- Anomaly detection (Bollinger, rolling z-score, SPC)
- Forecasting (ARIMA, Prophet) with confidence intervals
- Analytics narrative generation

Out of scope:
- Advanced causal inference frameworks
- Full MLOps training platform automation

Assumptions:
- Input time series is provided by the SQL Agent result.
- Models run in-process in v1 (no separate model server).

Constraints:
- Outputs MUST include uncertainty bounds.
- Forecasts MUST state the model used.

## 3. Methods
- Bollinger Bands, rolling z-score, SPC rules
- ARIMA, Prophet, moving-average fallback

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-09-001 | The analytics module MUST run a data quality check before applying any model. |
| FR-09-002 | The anomaly detector MUST return anomaly_points, anomaly_score, and anomaly_level. |
| FR-09-003 | The forecaster MUST return forecast_series, lower_bound, upper_bound, and model_used. |
| FR-09-004 | When a model fit fails, the system MUST fall back to moving-average extrapolation. |
| FR-09-005 | Output narratives MUST follow the structure: fact → model judgment → uncertainty. |
| FR-09-006 | The system MUST log the model version and parameters for each run. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-09-001 | Analytics stage latency P95 MUST be <= 6s after query data is available. |
| NFR-09-002 | Identical inputs MUST produce identical outputs (reproducibility). |
| NFR-09-003 | Model failure rate MUST trigger an alert when sustained above threshold. |

## 6. Model Selection Rules

| Condition | Method |
|---|---|
| Daily series, < 90 points | Prophet |
| Stationary or differenced series | ARIMA |
| Fit failure | Moving-average fallback |

## 7. Contracts

Input:
```
metric_id, time_series[], forecast_horizon, granularity, trace_id
```

Output:
```
anomaly_result, forecast_result, seasonality_summary,
confidence, warnings, trace_id
```

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-09-001 | A known anomalous series returns >= 1 anomaly_point with anomaly_level set. |
| AC-09-002 | A forecast result includes lower_bound, upper_bound, and model_used fields. |
| AC-09-003 | When model fitting fails, output contains fallback flag and moving-average result. |
| AC-09-004 | Output narrative contains all three sections: fact, judgment, uncertainty. |
| AC-09-005 | Analytics stage completes within 6s P95 for standard 90-day series. |

## 9. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-09-001 | Unit | Bollinger Band detects injected spike as anomaly. |
| TC-09-002 | Unit | Prophet forecast on clean series returns plausible intervals. |
| TC-09-003 | Unit | Moving-average fallback activates when ARIMA raises fit error. |
| TC-09-004 | Unit | Narrative builder produces fact/judgment/uncertainty structure. |
| TC-09-005 | Integration | SQL result → analytics → visualization chain completes under 6s. |
| TC-09-006 | Negative | Empty time series triggers data quality error, not model crash. |

## 10. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-09-001 | AC-09-001 | TC-09-006 |
| FR-09-002 | AC-09-001 | TC-09-001 |
| FR-09-003 | AC-09-002 | TC-09-002 |
| FR-09-004 | AC-09-003 | TC-09-003 |
| FR-09-005 | AC-09-004 | TC-09-004 |
| NFR-09-001 | AC-09-005 | TC-09-005 |

## 11. Open Questions
- OQ-09-001: Default model priority in v1?
- OQ-09-002: Holiday feature calendar configuration?
- OQ-09-003: Model drift monitoring dashboard?
