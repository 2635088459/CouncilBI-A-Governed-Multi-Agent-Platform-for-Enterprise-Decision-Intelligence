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

const root = document.querySelector("#chatbi-root");

function renderApp() {
  if (!root) {
    return;
  }

  root.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar" aria-label="Primary navigation">
        <div class="brand">InsightOps AI</div>
        <nav class="nav-list">
          <button class="nav-item is-active" type="button">Chat</button>
          <button class="nav-item" type="button">History</button>
          <button class="nav-item" type="button">Catalog</button>
          <button class="nav-item" type="button">Task</button>
          <button class="nav-item" type="button">Evaluation</button>
        </nav>
      </aside>
      <main class="workspace">
        <section class="toolbar" aria-label="Runtime configuration">
          <span>API ${escapeText(runtimeConfig.api_base_url)}</span>
          <span>${escapeText(runtimeConfig.environment)}</span>
          <span>${escapeText(runtimeConfig.locale_default)}</span>
        </section>
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
      </main>
    </div>
  `;

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

function escapeText(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

renderApp();
