# Spec: Frontend ChatBI

## 1. Purpose
Define the user-facing experience for submitting questions, viewing structured results, and replaying analysis sessions.

## 2. Scope
In scope:
- Chat page with multi-turn support
- Result rendering (table, chart, evidence, warnings)
- Query history and replay
- Metric catalog page
- Evaluation page

Out of scope:
- Native mobile app
- Drag-and-drop BI dashboard editor in v1

Assumptions:
- Chart schema is provided by the Visualization Agent.
- Frontend talks only to the Backend API, not to agents directly.

Constraints:
- Sensitive field values MUST NOT be cached in the browser.
- Export actions MUST be gated by backend permission checks.

## 3. Core Components
- MessageBubble, QueryResultCard, ChartCard
- SqlExplainCard, EvidenceCard
- RiskBanner, PartialFailureBanner

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-07-001 | Users MUST be able to submit a natural-language question and receive a structured answer. |
| FR-07-002 | Users MUST be able to ask follow-up questions in the same session. |
| FR-07-003 | The UI MUST render table, chart, evidence citations, and warnings as distinct blocks. |
| FR-07-004 | Chart type MUST follow the chart_spec from the backend; default chart for time series is line. |
| FR-07-005 | The UI MUST show an in-progress indicator while awaiting the answer. |
| FR-07-006 | Partial-failure responses MUST show available results with a visible warning banner. |
| FR-07-007 | Users MUST be able to browse and replay query history. |
| FR-07-008 | SQL explanation MUST be accessible from every answer card. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-07-001 | First meaningful render MUST be < 2s on a cache-hit response. |
| NFR-07-002 | UI interaction latency MUST be < 100ms. |
| NFR-07-003 | Core flows MUST be keyboard-accessible. |
| NFR-07-004 | CN/EN strings MUST be centralized in an i18n dictionary. |

## 6. Chart Mapping Rules

| Data type | Chart |
|---|---|
| Time series | Line |
| Category comparison | Bar |
| Proportion | Pie / Stacked bar |
| Anomaly | Line + markers |
| Forecast | History line + forecast + confidence band |

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-07-001 | A valid question returns a rendered answer card within 8s from submit. |
| AC-07-002 | A time-series result renders as a line chart. |
| AC-07-003 | A partial-failure response renders available content and a PartialFailureBanner. |
| AC-07-004 | Clicking "SQL Explain" shows the sql_text and sql_explanation fields. |
| AC-07-005 | History page lists past queries and clicking one replays it. |
| AC-07-006 | Submitting a question with the keyboard (Enter) works without mouse. |

## 8. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-07-001 | Unit | ChartCard renders line chart for time-series chart_spec. |
| TC-07-002 | Unit | PartialFailureBanner renders when warnings field is non-empty. |
| TC-07-003 | Unit | i18n function returns correct string for CN and EN locales. |
| TC-07-004 | Integration | Submit question → API returns → all result blocks render. |
| TC-07-005 | Integration | History list loads and replay works end-to-end. |
| TC-07-006 | Negative | Blocked SQL response renders safe message, no raw SQL leak. |
| TC-07-007 | Accessibility | Tab order covers input, send button, and result cards. |

## 9. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-07-001 | AC-07-001 | TC-07-004 |
| FR-07-003 | AC-07-002 | TC-07-001 |
| FR-07-004 | AC-07-002 | TC-07-001 |
| FR-07-006 | AC-07-003 | TC-07-002 |
| FR-07-007 | AC-07-005 | TC-07-005 |
| FR-07-008 | AC-07-004 | TC-07-004 |
| NFR-07-003 | AC-07-006 | TC-07-007 |

## 10. Open Questions
- OQ-07-001: ECharts or Recharts?
- OQ-07-002: SSE streaming responses in v1?
- OQ-07-003: Block-level copy and export actions?
