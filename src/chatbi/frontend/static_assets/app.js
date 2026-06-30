const runtimeConfig = window.__CHATBI_RUNTIME_CONFIG__ || {
  api_base_url: "/api",
  environment: "dev",
  locale_default: "en",
};

const fixtureAnswer = {
  question: "show monthly revenue",
  answerText: "Revenue trend is ready.",
  traceId: "trc_fixture_success",
  warning: "Fixture mode: this page is using local demo data.",
  table: [
    { order_month: "2026-01", revenue: "$125,000" },
    { order_month: "2026-02", revenue: "$141,500" },
    { order_month: "2026-03", revenue: "$153,200" },
  ],
  evidence: [
    "semantic.metrics: revenue",
    "runtime.query_results: trc_fixture_success",
  ],
};

const fixtureAnalytics = {
  traceId: "trc_fixture_analytics",
  metricId: "revenue",
  method: "linear_regression",
  modelVersion: "analytics-v2-rule-based-001",
  forecast: [
    { period: "2026-04", value: "$164,800" },
    { period: "2026-05", value: "$176,400" },
    { period: "2026-06", value: "$188,000" },
  ],
  warnings: ["Forecast uses fixture data for browser prototype mode."],
};

const root = document.querySelector("#chatbi-root");
let activeRoute = "chat";

function renderApp() {
  if (!root) {
    return;
  }

  root.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar" aria-label="Primary navigation">
        <div class="brand">InsightOps AI</div>
        <nav class="nav-list">
          ${renderNavItem("chat", "Chat")}
          ${renderNavItem("history", "History")}
          ${renderNavItem("catalog", "Catalog")}
          ${renderNavItem("analytics", "Analytics")}
          ${renderNavItem("task", "Task")}
          ${renderNavItem("evaluation", "Evaluation")}
        </nav>
      </aside>
      <main class="workspace">
        <section class="toolbar" aria-label="Runtime configuration">
          <span>API ${escapeText(runtimeConfig.api_base_url)}</span>
          <span>${escapeText(runtimeConfig.environment)}</span>
          <span>${escapeText(runtimeConfig.locale_default)}</span>
        </section>
        ${renderActivePage()}
      </main>
    </div>
  `;

  document.querySelectorAll("[data-route]").forEach((button) => {
    button.addEventListener("click", () => {
      activeRoute = button.getAttribute("data-route") || "chat";
      renderApp();
    });
  });

  document.querySelector("#submit-question")?.addEventListener("click", () => {
    const input = document.querySelector("#question-input");
    const question = input instanceof HTMLInputElement ? input.value : fixtureAnswer.question;
    const nextAnswer = { ...fixtureAnswer, question };
    const answerRegion = document.querySelector("#answer-region");
    if (answerRegion) {
      answerRegion.innerHTML = renderAnswer(nextAnswer);
    }
  });
}

function renderNavItem(route, label) {
  const activeClass = activeRoute === route ? " is-active" : "";
  return `
    <button class="nav-item${activeClass}" type="button" data-route="${escapeText(route)}">
      ${escapeText(label)}
    </button>
  `;
}

function renderActivePage() {
  if (activeRoute === "analytics") {
    return renderAnalytics(fixtureAnalytics);
  }

  return `
    <section class="chat-panel" aria-label="Chat workspace">
      <div class="question-row">
        <input
          id="question-input"
          class="question-input"
          value="${escapeText(fixtureAnswer.question)}"
          aria-label="Ask a business question"
        >
        <button id="submit-question" class="send-button" type="button">Submit</button>
      </div>
      <div id="answer-region" class="answer-region">
        ${renderAnswer(fixtureAnswer)}
      </div>
    </section>
  `;
}

function renderAnswer(answer) {
  return `
    <article class="answer-card">
      <div class="answer-header">
        <div>
          <p class="eyebrow">Answer</p>
          <h1>${escapeText(answer.answerText)}</h1>
        </div>
        <button class="trace-button" type="button" title="Copy trace id">
          ${escapeText(answer.traceId)}
        </button>
      </div>
      <p class="warning">${escapeText(answer.warning)}</p>
      <div class="result-grid">
        <section class="result-section" aria-label="Table result">
          <h2>Table</h2>
          <table>
            <thead>
              <tr><th>Month</th><th>Revenue</th></tr>
            </thead>
            <tbody>
              ${answer.table
                .map(
                  (row) => `
                    <tr>
                      <td>${escapeText(row.order_month)}</td>
                      <td>${escapeText(row.revenue)}</td>
                    </tr>
                  `,
                )
                .join("")}
            </tbody>
          </table>
        </section>
        <section class="result-section" aria-label="Chart result">
          <h2>Chart</h2>
          <div class="chart-bars">
            <span style="height: 48%"></span>
            <span style="height: 68%"></span>
            <span style="height: 84%"></span>
          </div>
        </section>
      </div>
      <section class="evidence" aria-label="Evidence list">
        <h2>Evidence</h2>
        <ul>
          ${answer.evidence.map((item) => `<li>${escapeText(item)}</li>`).join("")}
        </ul>
      </section>
    </article>
  `;
}

function renderAnalytics(analytics) {
  return `
    <section class="analytics-panel" aria-label="Analytics workspace">
      <article class="answer-card">
        <div class="answer-header">
          <div>
            <p class="eyebrow">Analytics</p>
            <h1>${escapeText(analytics.metricId)} forecast is ready.</h1>
          </div>
          <button class="trace-button" type="button" title="Copy trace id">
            ${escapeText(analytics.traceId)}
          </button>
        </div>
        <div class="analytics-meta">
          <span>Method ${escapeText(analytics.method)}</span>
          <span>Model ${escapeText(analytics.modelVersion)}</span>
        </div>
        <section class="result-section" aria-label="Forecast result">
          <h2>Forecast</h2>
          <div class="forecast-list">
            ${analytics.forecast
              .map(
                (point) => `
                  <div class="forecast-point">
                    <span>${escapeText(point.period)}</span>
                    <strong>${escapeText(point.value)}</strong>
                  </div>
                `,
              )
              .join("")}
          </div>
        </section>
        <section class="evidence" aria-label="Analytics warnings">
          <h2>Warnings</h2>
          <ul>
            ${analytics.warnings.map((item) => `<li>${escapeText(item)}</li>`).join("")}
          </ul>
        </section>
      </article>
    </section>
  `;
}

function escapeText(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

renderApp();
