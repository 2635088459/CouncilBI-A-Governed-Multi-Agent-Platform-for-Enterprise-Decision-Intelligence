# Spec v2: Analytics and Forecasting

Source design:
- [Chinese design](../../system_design/09-analytics-and-forecasting-design/VERSION2.zh-CN.md)
- [English design](../../system_design/09-analytics-and-forecasting-design/VERSION2.en.md)

## 1. Purpose
Define verifiable anomaly detection and forecasting service behavior for SQL-backed metric results. The implementation must make uncertainty explicit and degrade when data quality is insufficient.

## 2. Scope
In scope:
- Analytics input/output contract.
- Data quality checks.
- Synchronous small-data execution and asynchronous complex forecasting.
- Persistence of analytics parameters and results by trace id.

Out of scope:
- Full MLOps training platform.
- Advanced causal inference.
- Claims that forecasts are deterministic facts.

## 3. Typed Inputs and Outputs

### 3.1 AnalyticsRequest
Required fields:
- `trace_id: str`
- `metric_id: str`
- `semantic_version_id: str`
- `time_column: str`
- `value_column: str`
- `grain: Literal["day", "week", "month"]`
- `rows: list[TimeSeriesRow]`
- `analysis_options: AnalyticsOptions`

### 3.2 AnalyticsResult
Required fields:
- `anomaly_points: list[AnomalyPoint]`
- `forecast_points: list[ForecastPoint]`
- `confidence_interval: dict | null`
- `quality_warnings: list[str]`
- `method: str`
- `model_version: str`
- `explanation: str`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-09-001 | Rows MUST be sorted or sortable by `time_column`; invalid dates return `ANALYTICS_INVALID_TIME_SERIES`. | Negative test |
| VR-09-002 | Fewer than 3 data points MUST return trend summary only and warning `INSUFFICIENT_DATA`. | Boundary test |
| VR-09-003 | Forecast points MUST include lower and upper bounds with `lower <= value <= upper`. | Unit test |
| VR-09-004 | Analytics results MUST be persisted by `trace_id`. | Integration test |
| VR-09-005 | Async tasks MUST write final status `succeeded`, `failed`, or `timed_out`. | Worker test |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-09-001 | Service MUST validate time series input before analysis. |
| FR-09-002 | Service MUST run anomaly detection for eligible time series. |
| FR-09-003 | Service MUST run forecasting when enough historical rows exist. |
| FR-09-004 | Service MUST degrade to trend summary when quality checks fail. |
| FR-09-005 | Service MUST write analytics method, model version, parameters, and results to PostgreSQL. |
| FR-09-006 | Frontend-facing output MUST include anomaly points and forecast interval fields even when empty. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-09-001 | Analytics over 1,000 daily points MUST complete P95 <= 6000ms locally. |
| NFR-09-002 | Re-running deterministic rule-based analytics on the same input MUST produce identical anomaly point indexes. |
| NFR-09-003 | Pyright MUST report 0 errors for analytics contracts and result models. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-09-001 | Valid daily revenue fixture returns zero or more anomaly points and no validation error. |
| AC-09-002 | Two-point fixture returns warning `INSUFFICIENT_DATA` and empty forecast points. |
| AC-09-003 | Forecast fixture returns points with `lower <= value <= upper`. |
| AC-09-004 | Result row can be selected by `trace_id` and includes method and model version. |
| AC-09-005 | Same deterministic fixture run twice returns identical anomaly point dates. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-09-001 | pyright | Validate analytics request/result types. |
| TC-09-002 | pytest unit | Validate daily revenue fixture. |
| TC-09-003 | pytest boundary | Two-point fixture degrades with warning. |
| TC-09-004 | pytest unit | Forecast bounds are ordered correctly. |
| TC-09-005 | pytest integration | Persist result by trace id. |
| TC-09-006 | pytest determinism | Re-run deterministic fixture and compare anomaly dates. |
| TC-09-007 | benchmark | Measure 1,000-point analytics P95. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-09-001 | AC-09-001 | TC-09-002 |
| FR-09-002 | AC-09-001 | TC-09-002 |
| FR-09-003 | AC-09-003 | TC-09-004 |
| FR-09-004 | AC-09-002 | TC-09-003 |
| FR-09-005 | AC-09-004 | TC-09-005 |
| FR-09-006 | AC-09-002 | TC-09-003 |
| NFR-09-001 | AC-09-001 | TC-09-007 |
| NFR-09-002 | AC-09-005 | TC-09-006 |
| NFR-09-003 | AC-09-001 | TC-09-001 |

## 10. First Red-Green Steps
1. Define analytics request/result types.
2. Add validation for too-few points.
3. Implement one deterministic anomaly rule.
4. Persist one analytics result by trace id.

