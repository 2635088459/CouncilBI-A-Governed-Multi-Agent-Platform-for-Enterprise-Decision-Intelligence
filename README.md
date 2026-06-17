# Governed-Multi-Agent-ChatBI-Platform-for-Enterprise-Decision-Intelligence
---
---

## 1. Project Background

In real enterprise environments, business teams generate many data analysis requests every day. Product managers may want to understand why user activity dropped. Operations teams may want to know why revenue fluctuated in a specific region. Finance teams may want to forecast future revenue. Leadership teams may want to quickly identify abnormal KPI changes and understand the possible causes behind them.

Traditional BI dashboards are useful, but they are usually static. Users can only view pre-built charts and reports. When they have follow-up questions, they still need help from data analysts or data engineers. Many business users do not know SQL, so even simple questions often become tickets for the data team. This creates communication overhead, slow response time, and repetitive work.

With the rise of LLMs and AI agents, companies are exploring natural language analytics. However, directly allowing an LLM to generate SQL can be risky. The model may hallucinate table names, use incorrect fields, calculate metrics incorrectly, generate unsafe SQL, or provide unsupported explanations.

This project aims to build a more enterprise-ready ChatBI platform. Users can ask business questions in natural language, and the system coordinates multiple specialized agents to perform SQL querying, visualization, anomaly detection, forecasting, knowledge retrieval, and answer verification. The final output should be data-grounded, explainable, and auditable.

---

## 2. Project Goals

The goal of this project is to build an AI-powered data analysis platform with production-oriented engineering design.

The main goals are:

* Allow non-technical users to query structured business data using natural language.
* Use a semantic layer to standardize business metric definitions and reduce LLM misunderstanding.
* Use SQL guardrails to prevent unsafe queries, unauthorized access, and incorrect database operations.
* Use a multi-agent architecture to separate responsibilities and improve maintainability.
* Generate charts, summaries, anomaly detection results, and forecasting insights.
* Use RAG to retrieve business reports, product notes, incident logs, or external context to explain metric changes.
* Use a verifier agent to check SQL logic, calculation correctness, and final answer consistency.
* Add logging, query history, evaluation cases, and observability design to make the project closer to a real production system.

---

## 3. Industry Pain Points

This project is designed around several real industry pain points.

### 3.1 Business Teams Depend Heavily on Data Teams

Many business questions are not technically complex, but business users often cannot answer them because they do not know SQL or the database schema. They need analysts or engineers to manually query data, which creates a bottleneck.

InsightOps AI addresses this by allowing business users to ask questions in natural language and receive SQL-backed answers.

### 3.2 Dashboards Are Static and Do Not Support Flexible Follow-up Questions

Traditional dashboards can show revenue trends, conversion rates, or refund rates. However, they usually cannot answer follow-up questions such as:

* Why did this metric drop?
* Which product category caused the largest change?
* Was this change abnormal?
* Will the trend continue next month?
* Are there any business reports or incidents that explain this change?

InsightOps AI provides a conversational ChatBI workflow that combines SQL, charts, anomaly detection, forecasting, and RAG-based explanation.

### 3.3 LLM-Generated SQL Can Be Unreliable

A general-purpose LLM may generate SQL that is syntactically valid but logically wrong. It may use the wrong table, apply the wrong filter, calculate a business metric incorrectly, or generate unsafe SQL statements.

This project improves reliability through:

* Semantic layer
* SQL validation
* Read-only query enforcement
* Query timeout
* Row limit
* Role-based access control design
* Verifier agent
* Audit logging

### 3.4 Data Results Often Lack Business Explanation

Many BI systems can tell users what happened, but they do not explain why it happened. For example, a dashboard may show that revenue dropped in April, but it may not connect the drop to a marketing campaign pause, product issue, support incident, or external event.

InsightOps AI uses a RAG agent to retrieve relevant documents and provide evidence-based explanations.

### 3.5 Enterprises Need Forecasting and Anomaly Detection

Companies do not only need to look at historical data. They also need to detect risks early and understand future trends.

Example questions include:

* Is refund rate increasing abnormally?
* Is revenue entering a downward trend?
* Did user activity have an unusual drop?
* What is the expected order volume for the next 30 days?

InsightOps AI includes an analytics agent for forecasting and anomaly detection using methods such as ARIMA, Prophet, Bollinger Bands, rolling statistics, and SPC-style rules.

---

## 5. Project Positioning

InsightOps AI is positioned as:

**A multi-agent ChatBI platform for enterprise business data analysis.**

Users can ask natural language questions, and the system can automatically perform data querying, chart generation, metric explanation, anomaly detection, forecasting, and knowledge-grounded reasoning.

The project focuses on:

* Enterprise data analysis workflows
* Multi-agent task decomposition
* SQL safety and governance
* Explainable business insights
* Evaluation and reliability
* Full-stack engineering implementation
* Scalable system architecture

---

## 6. Target Users

### 6.1 Business Users

This includes product managers, operations teams, sales teams, finance teams, and leadership teams. These users may not know SQL, but they need fast and reliable business insights.

### 6.2 Data Analysts

Data analysts can use the system to reduce repetitive SQL requests and spend more time on complex analysis, metric design, and data quality improvement.

### 6.3 Engineering Teams

Engineering teams can use this project as an example of how to integrate LLMs, agents, databases, RAG, visualization, and security controls into an enterprise full-stack system.

---

## 7. Core Use Cases

### 7.1 Business KPI Query

Example user question:

```text
Show monthly revenue trend for 2024.
````

System workflow:

1. Understand the user intent.
2. Identify the revenue metric.
3. Use the semantic layer to locate the correct table and formula.
4. Generate SQL.
5. Validate SQL.
6. Execute the query.
7. Return a table, chart, and natural language summary.

### 7.2 Multi-Dimensional Comparison

Example user question:

```text
Compare revenue growth between California and New York in Q2.
```

System workflow:

1. Identify the comparison dimensions.
2. Query revenue data for both regions.
3. Calculate growth rate.
4. Generate a comparison chart.
5. Summarize which region grew faster and by how much.

### 7.3 Anomaly Detection

Example user question:

```text
Detect abnormal refund rate changes in the last 6 months.
```

System workflow:

1. Query refund rate time-series data.
2. Call the anomaly detection tool.
3. Mark abnormal dates.
4. Generate an anomaly chart.
5. Provide an initial explanation of the abnormal changes.

### 7.4 Trend Forecasting

Example user question:

```text
Predict revenue for the next 30 days.
```

System workflow:

1. Query historical revenue data.
2. Call ARIMA or Prophet forecasting tools.
3. Generate future trend predictions.
4. Return a forecast table and chart.
5. Add a warning that forecasting results should be interpreted with business context.

### 7.5 RAG-Based Explanation

Example user question:

```text
Why did user activity drop after the product release?
```

System workflow:

1. Query user activity changes.
2. Identify the time period of the drop.
3. Retrieve relevant product release notes, business reports, or incident logs.
4. Combine structured data and retrieved evidence.
5. Generate an evidence-grounded explanation.

---

## 8. Core System Features

### 8.1 Natural Language to SQL

The system converts natural language business questions into SQL queries.

Main capabilities:

* Understand database schema
* Identify business metrics
* Generate SQL
* Validate SQL
* Execute queries
* Summarize query results

### 8.2 Semantic Layer

The semantic layer standardizes business metric definitions.

Example:

```yaml
metrics:
  revenue:
    description: Total paid order amount
    table: orders
    formula: SUM(order_amount)
    filters:
      - status = 'paid'

  refund_rate:
    description: Refund amount divided by total paid order amount
    numerator: SUM(refund_amount)
    denominator: SUM(order_amount)
    filters:
      - status = 'paid'
```

Benefits:

1. Reduces LLM hallucination around metric definitions.
2. Ensures consistent calculation for the same metric.
3. Makes the system closer to real enterprise BI design.
4. Supports future permission control and auditability.

### 8.3 SQL Guardrail

SQL guardrail is one of the most important reliability components in this project.

Planned features:

* Allow only `SELECT` queries.
* Block dangerous operations such as `DROP`, `DELETE`, `UPDATE`, `INSERT`, and `ALTER`.
* Automatically add a row limit.
* Set query timeout.
* Check table-level and field-level access permissions.
* Record user question, generated SQL, execution time, and query status.
* Provide safe fallback messages when a query fails.

### 8.4 Automatic Visualization

The visualization agent selects the proper chart type based on the query result.

| Data Type               | Recommended Chart                     |
| ----------------------- | ------------------------------------- |
| Time series             | Line chart                            |
| Category comparison     | Bar chart                             |
| Proportion analysis     | Pie chart or stacked bar chart        |
| Multi-metric comparison | Grouped bar chart or multi-line chart |
| Anomaly detection       | Line chart with anomaly markers       |
| Forecasting             | Historical line plus forecast line    |

The goal is to make the output more readable and avoid using the same chart type for every query.

### 8.5 Analytics Agent

The analytics agent handles statistical and predictive analysis.

MVP methods:

* ARIMA forecasting
* Prophet time-series analysis
* Bollinger Bands anomaly detection
* Rolling mean and rolling standard deviation
* SPC-style anomaly rules

Future extensions:

* Isolation Forest
* Change point detection
* Causal analysis
* Cohort analysis
* Funnel analysis

### 8.6 RAG Agent

The RAG agent retrieves supporting information from business documents.

Possible document types:

* Weekly business reports
* Product release notes
* Marketing campaign records
* Customer support feedback
* Incident reports
* Financial reports
* Public news or external research

The goal is to help the system explain not only what changed, but also why it may have changed.

### 8.7 Verifier Agent

The verifier agent checks the reliability of the final output.

Main checks:

* Whether the SQL query is safe.
* Whether the SQL query matches the user question.
* Whether the correct metric definition is used.
* Whether there are obvious calculation errors.
* Whether the chart type matches the data.
* Whether the final answer is supported by query results and retrieved evidence.
* Whether uncertainty should be clearly stated.

The verifier agent is one of the main project highlights because it shows awareness of reliability issues in enterprise LLM systems.

---

## 9. Multi-Agent Architecture

The system uses an orchestrator agent with several specialized agents.

### 9.1 Orchestrator Agent

Responsibilities:

* Understand user questions.
* Classify the task type.
* Decompose the task into smaller steps.
* Route work to the correct specialized agents.
* Combine intermediate results into the final answer.

### 9.2 SQL Agent

Responsibilities:

* Generate SQL based on the user question and semantic layer.
* Explain the SQL logic.
* Call the SQL guardrail.
* Execute the validated SQL.
* Return structured query results.

### 9.3 Visualization Agent

Responsibilities:

* Select the proper chart type.
* Generate frontend-renderable chart specifications.
* Handle large result sets with sampling or aggregation.
* Support line charts, bar charts, comparison charts, and anomaly charts.

### 9.4 Analytics Agent

Responsibilities:

* Perform trend forecasting.
* Detect abnormal KPI changes.
* Analyze seasonality and periodic patterns.
* Explain metric fluctuations.
* Return model results and chart data.

### 9.5 RAG Agent

Responsibilities:

* Retrieve relevant documents.
* Extract possible causes.
* Provide supporting evidence.
* Avoid unsupported explanations.

### 9.6 Verifier Agent

Responsibilities:

* Check SQL safety.
* Validate metric calculation logic.
* Check whether the final answer is faithful to the data.
* Provide confidence signals or risk warnings.

---

## 10. Technical Architecture

### 10.1 Frontend

Technologies:

* React
* TypeScript
* Tailwind CSS
* ECharts or Recharts

Main pages:

1. ChatBI conversation page
2. Query result page
3. Chart display area
4. Query history page
5. Dataset and metric management page
6. Evaluation demo page

### 10.2 Backend

Technologies:

* FastAPI for AI service
* Spring Boot or FastAPI for main backend service
* PostgreSQL or MySQL as the main database
* Redis for caching
* pgvector or Qdrant as the vector database

### 10.3 AI and Agent Layer

Possible frameworks:

* LangGraph
* LlamaIndex
* Qwen-Agent
* Nanobot

For the first version, agents can be implemented as Python classes or modules. After the core workflow works, the system can be migrated to LangGraph or Nanobot for better orchestration.

### 10.4 Data Layer

The MVP should use a simulated enterprise business dataset instead of only stock data.

Suggested tables:

* orders
* products
* customers
* regions
* refunds
* marketing_campaigns
* web_events
* support_tickets

Core metrics:

* revenue
* order_count
* refund_rate
* active_users
* conversion_rate
* churn_rate
* average_order_value
* support_ticket_volume

This makes the project more relevant to enterprise analytics than a pure stock analysis assistant.

---

## 11. End-to-End System Workflow

Example user question:

```text
Why did revenue drop in April, and will it continue to drop next month?
```

System workflow:

1. The orchestrator agent identifies the task as metric analysis, anomaly detection, forecasting, and explanation.
2. The SQL agent queries revenue data.
3. The visualization agent generates a revenue trend chart.
4. The analytics agent checks whether the April revenue drop is abnormal and predicts the future trend.
5. The RAG agent retrieves April business reports and marketing campaign notes.
6. The verifier agent checks whether the SQL, chart, forecast, and explanation are consistent.
7. The orchestrator agent produces the final analytical answer.

Final output includes:

* Revenue trend chart
* April revenue drop percentage
* Main contributing dimensions
* Abnormality detection result
* Future trend forecast
* Possible causes
* Supporting evidence
* Uncertainty warning

---

## 12. Project Directory Plan

```text
insightops-ai/
├── frontend/
│   ├── src/
│   ├── components/
│   ├── pages/
│   └── package.json
│
├── backend/
│   ├── app/
│   ├── api/
│   ├── services/
│   ├── agents/
│   ├── tools/
│   ├── db/
│   └── main.py
│
├── data/
│   ├── seed.sql
│   ├── business_kpi_sample.csv
│   └── reports/
│
├── semantic_layer/
│   └── metrics.yaml
│
├── prompts/
│   ├── orchestrator_prompt.md
│   ├── sql_agent_prompt.md
│   ├── verifier_prompt.md
│   └── rag_prompt.md
│
├── evals/
│   ├── questions.json
│   ├── expected_sql.json
│   └── evaluation_report.md
│
├── docs/
│   ├── project-plan.md
│   ├── design-doc.md
│   ├── architecture.md
│   └── demo-script.md
│
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 14. MVP Scope

To finish the project within 14 days, the MVP scope needs to be controlled.

### Must Have

* Enterprise-style business dataset
* NL2SQL querying
* SQL guardrail
* Table result display
* Chart display
* Basic multi-agent architecture
* Anomaly detection
* Forecasting
* RAG-based explanation
* Verifier agent MVP
* GitHub README
* Design document
* Demo video

### Can Be Deferred

* Full RBAC implementation
* Kubernetes
* Prometheus and Grafana
* Multi-tenancy
* Complex permission system
* Large-scale data optimization
* ClickHouse
* Advanced causal inference
* Full production deployment

---

## 15. Evaluation Plan

The project should include evaluation design so that it does not look like a simple demo.

### 15.1 SQL Accuracy

Evaluate whether the generated SQL matches the user question.

Metrics:

* Correct table selection
* Correct field selection
* Correct aggregation function
* Correct time filter
* Correct metric definition

### 15.2 SQL Safety

Test whether the system blocks unsafe SQL.

Example unsafe SQL:

```sql
DROP TABLE orders;
DELETE FROM customers;
UPDATE orders SET amount = 0;
SELECT * FROM customers;
```

The system should block dangerous operations and restrict sensitive tables or fields.

### 15.3 Agent Routing

Evaluate whether the orchestrator selects the correct agents.

| User Question               | Expected Agents                          |
| --------------------------- | ---------------------------------------- |
| Show revenue by month       | SQL Agent + Visualization Agent          |
| Predict revenue next month  | SQL Agent + Analytics Agent              |
| Why did revenue drop?       | SQL Agent + RAG Agent + Verifier Agent   |
| Detect abnormal refund rate | SQL Agent + Analytics Agent              |
| Explain this chart          | Visualization Agent + Orchestrator Agent |

### 15.4 RAG Faithfulness

Check whether the final answer is supported by retrieved documents instead of being hallucinated.

Evaluation criteria:

* Whether the correct documents are retrieved
* Whether unsupported claims are avoided
* Whether facts and assumptions are separated
* Whether uncertainty is clearly stated

### 15.5 Latency

Track response time for different workflow components:

* SQL query latency
* RAG retrieval latency
* Forecasting latency
* Full agent workflow latency

---

## 16. Project Highlights

The main highlights of this project are:

* Uses a multi-agent architecture instead of a single chatbot.
* Combines NL2SQL, RAG, BI visualization, forecasting, and anomaly detection.
* Introduces a semantic layer to show enterprise metric governance thinking.
* Implements SQL guardrails to improve system safety.
* Uses a verifier agent to reduce hallucination and incorrect analysis.
* Provides a full-stack implementation with frontend, backend, database, and AI service.
* Includes an evaluation suite to demonstrate engineering quality.
* Aligns with the industry trend of AI-powered BI and agentic analytics.

---

## 17. Final Project Summary

InsightOps AI is a multi-agent ChatBI platform for enterprise business data analysis. It combines LLM agents, NL2SQL, RAG, BI visualization, anomaly detection, forecasting, and SQL safety governance to help business users obtain trustworthy data insights through natural language.

The project is not a simple chatbot. It demonstrates how LLMs can be integrated into real enterprise data workflows while addressing reliability, safety, explainability, and engineering challenges.

```
```

---

## 18. Minimal Overall Architecture Slice

This repository now includes a small runnable slice for `spec/01-overall-architecture.spec.md`.

In plain English, the current slice proves this workflow:

```text
API request
  -> ChatBIApplication
  -> SimpleOrchestrator
  -> SimpleSqlGuardrail
  -> InMemoryQueryHistory
  -> API envelope response
```

The goal is not to finish the whole platform at once. The goal is to make one small architecture loop verifiable before adding more agents, databases, or LLM calls.

### Files

| File | Purpose |
|---|---|
| `src/chatbi/core/contracts.py` | Core typed contracts: request, answer, trace, guardrail result, history record |
| `src/chatbi/history/in_memory.py` | In-memory query history and replay by `trace_id` |
| `src/chatbi/governance/simple_guardrail.py` | Minimal SQL guardrail: allow single `SELECT`, block dangerous statements |
| `src/chatbi/orchestration/simple_orchestrator.py` | Routes request through guardrail, builds answer, saves history |
| `src/chatbi/api/models.py` | API request/response payload and unified envelope models |
| `src/chatbi/application/app.py` | Pure Python application facade |
| `src/chatbi/api/http.py` | FastAPI app exposing `POST /api/v1/chat/query` |

### Run Static Checks

```bash
python3 -m py_compile src/chatbi/*.py tests/*.py
```

### Install Dev Dependencies

```bash
python3 -m pip install -e ".[dev]"
```

### Run Tests

```bash
python3 -m pytest
```

### Run The HTTP API

```bash
python3 -m uvicorn chatbi.api.http:app --app-dir src --reload
```

Then call:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat/query \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_001",
    "session_id": "s_001",
    "question": "Show revenue trend.",
    "locale": "en",
    "role": "business_user"
  }'
```

Expected shape:

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "answer_text": "Revenue trend is ready.",
    "sql_text": "SELECT month, revenue FROM revenue_by_month LIMIT 100"
  },
  "trace_id": "trc_...",
  "warnings": []
}
```
