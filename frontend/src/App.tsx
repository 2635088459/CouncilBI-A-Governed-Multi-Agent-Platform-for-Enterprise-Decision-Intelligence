import { FormEvent, useRef, useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

type ApiState = "idle" | "loading" | "success" | "error";

type WarningItem = string | { code?: string; message?: string; field?: string };

type ChartSpec = {
  chart_type?: string;
  x_field?: string;
  y_fields?: string[];
  title?: string;
};

type AgentTimelineItem = {
  agent_name?: string;
  status?: string;
  duration_ms?: number | null;
  summary?: string | null;
  agent_trace_id?: string | null;
};

type EvidenceCard = {
  source_id?: string;
  title?: string;
  citation_anchor?: string;
  snippet?: string;
  source?: string;
  url?: string;
  relevance_score?: number;
};

type ApiError = { code?: string; message?: string; retryable?: boolean; detail?: unknown };

type ChatResponse = {
  trace_id?: string;
  request_id?: string;
  data?: {
    answer_text?: string;
    answer?: string;
    sql?: string;
    table_result?: { columns?: string[]; rows?: Array<Record<string, unknown>> };
    rows?: Array<Record<string, unknown>>;
    chart_spec?: ChartSpec;
    citations?: EvidenceCard[];
    evidence_list?: EvidenceCard[];
    agent_timeline?: AgentTimelineItem[];
  };
  warnings?: WarningItem[];
  error?: ApiError | null;
};

type LoginResponse = {
  data?: {
    user?: { user_id?: string; email?: string; display_name?: string; roles?: string[] };
    tokens?: { access_token?: string; refresh_token?: string; expires_in?: number };
  };
};

type AuditRecord = {
  trace_id: string;
  user_id: string;
  role: string;
  question: string;
  answer_text?: string;
  status: string;
  error_code?: string;
  blocked: boolean;
  sql_row_count?: number;
  rag_doc_count?: number;
  has_chart: boolean;
  latency_ms?: number;
  accepted_at: string;
  evidence?: Array<{ source_id: string; title: string; snippet: string }>;
};

type AuditStats = {
  total: number;
  succeeded: number;
  failed: number;
  blocked: number;
  success_rate: number;
  avg_latency_ms: number;
  unique_users: number;
};

// ─── Constants ────────────────────────────────────────────────────────────────

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

const SAMPLE_QUESTIONS = [
  "Compare total ticket count by product in H1 2026.",
  "Show me monthly revenue trend for 2026.",
  "Which product has the worst average resolution time for critical issues?",
  "What caused the July 2026 revenue drop?",
];

// ─── Utilities ────────────────────────────────────────────────────────────────

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`;
}

function newSessionId() {
  return `ses_${Math.random().toString(36).slice(2, 10)}`;
}

function requestIdStr() {
  return `req_fe_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

async function postJson<T>(path: string, body: unknown, token?: string): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Request-Id": requestIdStr(),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(apiUrl(path), { method: "POST", headers, body: JSON.stringify(body) });
  const payload = (await resp.json().catch(() => ({}))) as T;
  if (!resp.ok) {
    const err = payload as { error?: ApiError; detail?: string };
    const msg = err.error?.message ?? err.detail ?? `HTTP ${resp.status}`;
    const code = err.error?.code;
    const e = new Error(msg) as Error & { errorCode?: string };
    if (code) e.errorCode = code;
    throw e;
  }
  return payload;
}

async function getJson<T>(path: string, token: string): Promise<T> {
  const resp = await fetch(apiUrl(path), {
    headers: { Authorization: `Bearer ${token}`, "X-Request-Id": requestIdStr() },
  });
  const payload = (await resp.json().catch(() => ({}))) as T;
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return payload;
}

function resolveAnswer(r?: ChatResponse) {
  return r?.data?.answer_text ?? r?.data?.answer;
}
function resolveRows(r?: ChatResponse) {
  return r?.data?.table_result?.rows ?? r?.data?.rows ?? [];
}
function resolveCitations(r?: ChatResponse): EvidenceCard[] {
  return r?.data?.citations ?? r?.data?.evidence_list ?? [];
}
function resolveChart(r?: ChatResponse) {
  return r?.data?.chart_spec;
}
function resolveTimeline(r?: ChatResponse): AgentTimelineItem[] {
  return r?.data?.agent_timeline ?? [];
}

function readableAgentName(v?: string) {
  if (!v) return "Agent";
  return v
    .replace(/_agent$/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function numericValue(v: unknown): number | undefined {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
  }
}

function fmtNum(n: number) {
  return n % 1 === 0 ? String(n) : n.toFixed(1);
}

function warningText(w: WarningItem) {
  if (typeof w === "string") return w;
  return [w.field, w.code, w.message].filter(Boolean).join(" · ");
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cls = status === "succeeded" ? "badge-ok"
    : status === "failed" || status === "error" ? "badge-err"
    : status === "skipped" ? "badge-skip"
    : "badge-neu";
  return <span className={`status-badge ${cls}`}>{status}</span>;
}

function ChartPanel({ spec, rows }: { spec?: ChartSpec; rows: Array<Record<string, unknown>> }) {
  const xField = spec?.x_field;
  const yField = spec?.y_fields?.[0];
  if (!xField || !yField || rows.length < 2) return null;

  const pts = rows
    .map((r) => ({ label: String(r[xField] ?? ""), value: numericValue(r[yField]) }))
    .filter((p): p is { label: string; value: number } => p.label !== "" && p.value !== undefined);
  if (pts.length < 2) return null;

  const W = 720, H = 220, pad = { t: 22, r: 22, b: 44, l: 60 };
  const min = Math.min(...pts.map((p) => p.value));
  const max = Math.max(...pts.map((p) => p.value));
  const span = max - min || 1;
  const xs = (W - pad.l - pad.r) / (pts.length - 1);
  const ys = H - pad.t - pad.b;

  const pathD = pts.map((p, i) => {
    const x = pad.l + i * xs;
    const y = pad.t + ys - ((p.value - min) / span) * ys;
    return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");

  const areaD = [
    ...pts.map((p, i) => {
      const x = pad.l + i * xs;
      const y = pad.t + ys - ((p.value - min) / span) * ys;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }),
    `L ${(pad.l + (pts.length - 1) * xs).toFixed(1)} ${(pad.t + ys).toFixed(1)}`,
    `L ${pad.l} ${(pad.t + ys).toFixed(1)} Z`,
  ].join(" ");

  const tickStep = Math.ceil(pts.length / 7);

  return (
    <section className="chart-wrap" aria-label={spec?.title ?? "Chart"}>
      {spec?.title && <p className="chart-title">{spec.title}</p>}
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img" aria-label={`${yField} by ${xField}`}>
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0c5450" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#0c5450" stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = pad.t + ys * (1 - t);
          const val = min + t * span;
          return (
            <g key={t}>
              <line x1={pad.l} y1={y} x2={W - pad.r} y2={y} stroke="#e0eaeb" strokeWidth="1" strokeDasharray={t === 0 ? "none" : "3 3"} />
              <text x={pad.l - 8} y={y + 4} textAnchor="end" className="chart-tick">{fmtNum(val)}</text>
            </g>
          );
        })}
        {/* Area fill */}
        <path d={areaD} fill="url(#areaGrad)" />
        {/* Line */}
        <path d={pathD} className="chart-line" />
        {/* Points + x labels */}
        {pts.map((p, i) => {
          const x = pad.l + i * xs;
          const y = pad.t + ys - ((p.value - min) / span) * ys;
          const showLabel = i === 0 || i === pts.length - 1 || i % tickStep === 0;
          return (
            <g key={i}>
              {showLabel && <text x={x} y={H - 8} textAnchor="middle" className="chart-tick">{p.label}</text>}
              <circle cx={x} cy={y} r="4" className="chart-dot" />
            </g>
          );
        })}
      </svg>
    </section>
  );
}

function DataTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]);
  const display = rows.slice(0, 10);
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {display.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => <td key={c}>{String(row[c] ?? "—")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 10 && <p className="table-more">Showing 10 of {rows.length} rows</p>}
    </div>
  );
}

function EvidenceSection({ items }: { items: EvidenceCard[] }) {
  if (!items.length) return null;
  return (
    <div className="evidence-section">
      <p className="section-eyebrow">Sources</p>
      <div className="evidence-list">
        {items.map((c, i) => (
          <div className="evidence-item" key={i}>
            <div className="evidence-item-header">
              <strong>{c.title ?? c.source ?? c.url ?? "Source"}</strong>
              <code className="source-id">{c.citation_anchor ?? c.source_id ?? ""}</code>
            </div>
            {c.snippet && <p className="evidence-snippet">{c.snippet}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentTimeline({ items, open, onToggle }: {
  items: AgentTimelineItem[];
  open: boolean;
  onToggle: () => void;
}) {
  if (!items.length) return null;
  return (
    <div className="timeline-section">
      <button className="timeline-toggle" onClick={onToggle} type="button">
        <span className="section-eyebrow">Agent Activity</span>
        <span className="toggle-arrow">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="timeline-list">
          {items.map((item, i) => (
            <div className="timeline-step" key={i}>
              <div className="timeline-step-top">
                <strong className="agent-name">{readableAgentName(item.agent_name)}</strong>
                <StatusBadge status={item.status ?? "unknown"} />
              </div>
              {item.summary && <p className="timeline-summary">{item.summary}</p>}
              <div className="timeline-meta">
                <span>{item.duration_ms != null ? `${item.duration_ms} ms` : "—"}</span>
                {item.agent_trace_id && <code className="source-id">{item.agent_trace_id}</code>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Login Screen ─────────────────────────────────────────────────────────────

function LoginScreen({ onSuccess }: { onSuccess: (token: string, email: string) => void }) {
  const [email, setEmail] = useState("analyst@example.com");
  const [password, setPassword] = useState("");
  const [loginState, setLoginState] = useState<ApiState>("idle");
  const [errorMsg, setErrorMsg] = useState("");

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setLoginState("loading");
    setErrorMsg("");
    try {
      const resp = await postJson<LoginResponse>("/api/v2/auth/signin", { email, password });
      const token = resp.data?.tokens?.access_token;
      if (!token) throw new Error("No access token in response");
      const displayEmail = resp.data?.user?.email ?? email;
      onSuccess(token, displayEmail);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Sign in failed");
      setLoginState("error");
    }
  }

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="login-brand">
          <svg className="brand-hex" viewBox="0 0 40 46" aria-hidden="true">
            <polygon points="20,2 38,12 38,34 20,44 2,34 2,12" fill="none" stroke="#0c5450" strokeWidth="2.5" />
            <polygon points="20,9 31,15.5 31,28.5 20,35 9,28.5 9,15.5" fill="#0c5450" opacity="0.15" />
            <text x="20" y="27" textAnchor="middle" fontSize="14" fontWeight="800" fill="#0c5450">BI</text>
          </svg>
          <h1 className="login-title">Governed ChatBI</h1>
          <p className="login-sub">Enterprise Decision Intelligence</p>
        </div>

        <form className="login-form" onSubmit={handleLogin}>
          <label className="form-label">
            Email
            <input
              className="form-input"
              type="email"
              value={email}
              autoComplete="email"
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label className="form-label">
            Password
            <input
              className="form-input"
              type="password"
              value={password}
              autoComplete="current-password"
              placeholder="••••••••"
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {loginState === "error" && <p className="form-error">{errorMsg}</p>}
          <button className="login-btn" type="submit" disabled={loginState === "loading"}>
            {loginState === "loading" ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="login-hint">
          <span>Demo accounts:</span>
          <div className="hint-accounts">
            <code>analyst@example.com</code><span>/</span><code>demo1234</code>
          </div>
          <div className="hint-accounts">
            <code>admin@acme.com</code><span>/</span><code>admin1234</code>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Admin Dashboard ──────────────────────────────────────────────────────────

function statusColor(status: string): string {
  if (status === "succeeded") return "#22c55e";
  if (status === "blocked") return "#f59e0b";
  if (status === "failed") return "#ef4444";
  return "#94a3b8";
}

function AuditStatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="audit-stat-card">
      <div className="audit-stat-value">{value}</div>
      <div className="audit-stat-label">{label}</div>
      {sub && <div className="audit-stat-sub">{sub}</div>}
    </div>
  );
}

function AdminDashboard({ token }: { token: string }) {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [total, setTotal] = useState(0);
  const [loadState, setLoadState] = useState<ApiState>("idle");
  const [filterUser, setFilterUser] = useState("");
  const [filterStatus, setFilterStatus] = useState("all");
  const [filterFrom, setFilterFrom] = useState("");
  const [filterTo, setFilterTo] = useState("");
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const pageSize = 20;

  async function load(pg = 0) {
    setLoadState("loading");
    try {
      const params = new URLSearchParams();
      if (filterUser.trim()) params.set("user_id", filterUser.trim());
      if (filterStatus !== "all") params.set("status", filterStatus);
      if (filterFrom) params.set("from_date", filterFrom);
      if (filterTo) params.set("to_date", filterTo);
      params.set("limit", String(pageSize));
      params.set("offset", String(pg * pageSize));
      const resp = await getJson<{ data: { items: AuditRecord[]; total: number; stats: AuditStats } }>(
        `/api/v2/admin/query-audit?${params}`, token
      );
      setRecords(resp?.data?.items ?? []);
      setTotal(resp?.data?.total ?? 0);
      setStats(resp?.data?.stats ?? null);
      setPage(pg);
      setLoadState("success");
    } catch {
      setLoadState("error");
    }
  }

  function fmtTime(iso: string) {
    const d = new Date(iso);
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function fmtLatency(ms?: number) {
    if (!ms) return "—";
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="admin-dashboard">
      {/* Stats row */}
      {stats && (
        <div className="audit-stats-row">
          <AuditStatCard label="Total Queries" value={stats.total} />
          <AuditStatCard label="Success Rate" value={`${stats.success_rate}%`} sub={`${stats.succeeded} succeeded`} />
          <AuditStatCard label="Blocked" value={stats.blocked} sub="by guardrail" />
          <AuditStatCard label="Failed" value={stats.failed} />
          <AuditStatCard label="Avg Latency" value={fmtLatency(stats.avg_latency_ms)} />
          <AuditStatCard label="Unique Users" value={stats.unique_users} />
        </div>
      )}

      {/* Filter bar */}
      <div className="audit-filter-bar">
        <input
          className="audit-filter-input"
          placeholder="Filter by user email…"
          value={filterUser}
          onChange={(e) => setFilterUser(e.target.value)}
        />
        <select className="audit-filter-select" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
          <option value="all">All status</option>
          <option value="succeeded">Succeeded</option>
          <option value="failed">Failed</option>
          <option value="blocked">Blocked</option>
        </select>
        <input type="date" className="audit-filter-input date" value={filterFrom} onChange={(e) => setFilterFrom(e.target.value)} />
        <span className="audit-filter-sep">→</span>
        <input type="date" className="audit-filter-input date" value={filterTo} onChange={(e) => setFilterTo(e.target.value)} />
        <button className="audit-load-btn" onClick={() => load(0)} disabled={loadState === "loading"}>
          {loadState === "loading" ? "Loading…" : "Load"}
        </button>
      </div>

      {/* Table */}
      {loadState === "idle" && (
        <div className="audit-empty">Click <strong>Load</strong> to view query audit log.</div>
      )}
      {loadState === "success" && records.length === 0 && (
        <div className="audit-empty">No records found.</div>
      )}
      {records.length > 0 && (
        <>
          <div className="audit-table-wrap">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>User</th>
                  <th>Role</th>
                  <th>Question</th>
                  <th>Status</th>
                  <th>Latency</th>
                  <th>SQL</th>
                  <th>RAG</th>
                  <th>Chart</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <>
                    <tr
                      key={r.trace_id}
                      className={`audit-row ${expandedTrace === r.trace_id ? "expanded" : ""}`}
                      onClick={() => setExpandedTrace(expandedTrace === r.trace_id ? null : r.trace_id)}
                    >
                      <td className="audit-cell-time">{fmtTime(r.accepted_at)}</td>
                      <td className="audit-cell-user" title={r.user_id}>{r.user_id.split("@")[0]}</td>
                      <td><span className="audit-role-chip">{r.role}</span></td>
                      <td className="audit-cell-question" title={r.question}>{r.question.slice(0, 72)}{r.question.length > 72 ? "…" : ""}</td>
                      <td>
                        <span className="audit-status-dot" style={{ background: statusColor(r.status) }} />
                        {r.status}
                      </td>
                      <td>{fmtLatency(r.latency_ms)}</td>
                      <td>{r.sql_row_count ?? "—"}</td>
                      <td>{r.rag_doc_count ?? "—"}</td>
                      <td>{r.has_chart ? "✓" : "—"}</td>
                    </tr>
                    {expandedTrace === r.trace_id && (
                      <tr key={`${r.trace_id}-detail`} className="audit-detail-row">
                        <td colSpan={9}>
                          <div className="audit-detail">
                            <div className="audit-detail-meta">
                              <code className="trace-chip">{r.trace_id}</code>
                              {r.error_code && <span className="audit-error-chip">{r.error_code}</span>}
                            </div>
                            {r.answer_text && (
                              <div className="audit-detail-section">
                                <p className="audit-detail-label">Answer</p>
                                <p className="audit-detail-answer">{r.answer_text}</p>
                              </div>
                            )}
                            {r.evidence && r.evidence.length > 0 && (
                              <div className="audit-detail-section">
                                <p className="audit-detail-label">Evidence ({r.evidence.length} sources)</p>
                                {r.evidence.map((e, i) => (
                                  <div className="audit-evidence-item" key={i}>
                                    <span className="audit-evidence-source">{e.source_id}</span>
                                    <span className="audit-evidence-snippet">{e.snippet}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div className="audit-pagination">
              <button disabled={page === 0} onClick={() => load(page - 1)}>← Prev</button>
              <span>Page {page + 1} of {totalPages} ({total} total)</span>
              <button disabled={page >= totalPages - 1} onClick={() => load(page + 1)}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [token, setToken] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [role, setRole] = useState("analyst");
  const [locale, setLocale] = useState("en");
  const [question, setQuestion] = useState(SAMPLE_QUESTIONS[0]);
  const [chatState, setChatState] = useState<ApiState>("idle");
  const [chatErrorCode, setChatErrorCode] = useState("");
  const [chatResponse, setChatResponse] = useState<ChatResponse | undefined>();
  const [chatError, setChatError] = useState("");
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [devOpen, setDevOpen] = useState(false);
  const [adminPayload, setAdminPayload] = useState<unknown>(null);
  const [adminState, setAdminState] = useState<ApiState>("idle");
  const [activeTab, setActiveTab] = useState<"chat" | "admin">("chat");

  const sessionId = useRef(newSessionId()).current;
  const isAdmin = role === "admin";

  const isLoggedIn = Boolean(token);

  function handleLoginSuccess(newToken: string, email: string) {
    setToken(newToken);
    setUserEmail(email);
  }

  function handleLogout() {
    setToken("");
    setUserEmail("");
    setChatState("idle");
    setChatResponse(undefined);
  }

  async function submitQuestion(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setChatState("loading");
    setChatError("");
    setChatErrorCode("");
    setChatResponse(undefined);
    try {
      const payload = await postJson<ChatResponse>(
        "/api/v2/chat/query",
        { request_id: requestIdStr(), user_id: userEmail || "frontend-user", session_id: sessionId, question, locale, role },
        token
      );
      setChatResponse(payload);
      if (payload.error) {
        setChatState("error");
        setChatErrorCode(payload.error.code ?? "");
        setChatError(payload.error.message ?? payload.error.code ?? "An error occurred.");
      } else {
        setChatState("success");
      }
    } catch (err) {
      setChatState("error");
      const e = err as Error & { errorCode?: string };
      setChatErrorCode(e.errorCode ?? "");
      setChatError(e.message || String(err));
    }
  }

  async function loadAdmin() {
    setAdminState("loading");
    setDevOpen(true);
    try {
      const payload = await getJson<unknown>("/api/v2/admin/observability/summary", token);
      setAdminPayload(payload);
      setAdminState("success");
    } catch (err) {
      setAdminPayload({ error: err instanceof Error ? err.message : String(err) });
      setAdminState("error");
    }
  }

  if (!isLoggedIn) {
    return <LoginScreen onSuccess={handleLoginSuccess} />;
  }

  const answer = resolveAnswer(chatResponse);
  const rows = resolveRows(chatResponse);
  const citations = resolveCitations(chatResponse);
  const chart = resolveChart(chatResponse);
  const timeline = resolveTimeline(chatResponse);
  const warnings = chatResponse?.warnings ?? [];
  const traceId = chatResponse?.trace_id;

  const roleBadgeClass = role === "admin" ? "role-badge admin" : "role-badge analyst";

  return (
    <div className="app-shell">
      {/* ── Top nav ── */}
      <nav className="app-nav">
        <div className="nav-brand">
          <svg className="nav-hex" viewBox="0 0 28 32" aria-hidden="true">
            <polygon points="14,1.5 26.5,8.5 26.5,23.5 14,30.5 1.5,23.5 1.5,8.5" fill="none" stroke="#4fc0b6" strokeWidth="1.8" />
            <text x="14" y="21" textAnchor="middle" fontSize="10" fontWeight="800" fill="#a8e8e3">BI</text>
          </svg>
          <span className="nav-wordmark">Governed ChatBI</span>
        </div>
        <div className="nav-right">
          <span className={roleBadgeClass}>{role}</span>
          <span className="nav-user">{userEmail}</span>
          <select
            className="locale-select"
            value={locale}
            onChange={(e) => setLocale(e.target.value)}
            aria-label="Language"
          >
            <option value="en">EN</option>
            <option value="zh-CN">中文</option>
          </select>
          <button className="logout-btn" onClick={handleLogout} type="button">Sign out</button>
        </div>
      </nav>

      {/* ── Body ── */}
      <div className="app-body">
        {/* ── Sidebar ── */}
        <aside className="sidebar">
          <div className="sidebar-block">
            <p className="sidebar-label">Quick questions</p>
            <div className="question-chips">
              {SAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  className={`question-chip ${question === q ? "active" : ""}`}
                  type="button"
                  onClick={() => setQuestion(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
          <div className="sidebar-block">
            <p className="sidebar-label">Viewing as</p>
            <select
              className="role-select"
              value={role}
              onChange={(e) => setRole(e.target.value)}
            >
              <option value="analyst">Analyst</option>
              <option value="admin">Admin</option>
              <option value="viewer">Viewer</option>
            </select>
            <p className="sidebar-hint">
              {role === "admin" ? "Full data access including P0 fields." :
               role === "analyst" ? "P0 fields masked. Aggregates visible." :
               "Read-only. Aggregates only."}
            </p>
          </div>
          <div className="sidebar-block">
            <button className="sidebar-admin-btn" type="button" onClick={loadAdmin}>
              Load admin summary
            </button>
          </div>
        </aside>

        {/* ── Main content ── */}
        <main className="main-content">
          {/* Tab bar — only show Admin tab when role is admin */}
          {isAdmin && (
            <div className="tab-bar">
              <button
                className={`tab-btn ${activeTab === "chat" ? "active" : ""}`}
                type="button"
                onClick={() => setActiveTab("chat")}
              >
                Chat Query
              </button>
              <button
                className={`tab-btn ${activeTab === "admin" ? "active" : ""}`}
                type="button"
                onClick={() => setActiveTab("admin")}
              >
                Admin Audit
              </button>
            </div>
          )}

          {/* Admin dashboard */}
          {activeTab === "admin" && isAdmin && (
            <AdminDashboard token={token} />
          )}

          {/* Question form + answer — hidden when admin tab active */}
          {activeTab === "chat" && (
          <div className="chat-tab-content">
          <form className="question-form" onSubmit={submitQuestion}>
            <div className="question-form-inner">
              <textarea
                className="question-input"
                value={question}
                rows={3}
                placeholder="Ask a business question in plain English…"
                onChange={(e) => setQuestion(e.target.value)}
                aria-label="Business question"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitQuestion(e as unknown as FormEvent);
                }}
              />
              <button
                className="run-btn"
                type="submit"
                disabled={chatState === "loading" || !question.trim()}
              >
                {chatState === "loading" ? (
                  <><span className="spinner" aria-hidden="true" /> Running…</>
                ) : "Run query"}
              </button>
            </div>
            <p className="question-hint">⌘ Enter to run · Role: <strong>{role}</strong></p>
          </form>

          {/* Answer area */}
          {chatState !== "idle" && (
            <div className="answer-area">
              {/* Header bar */}
              <div className={`answer-header ${chatState}`}>
                <div className="answer-header-left">
                  <span className="answer-label">Answer</span>
                  {traceId && <code className="trace-chip">{traceId}</code>}
                </div>
                <StatusBadge status={chatState === "loading" ? "running" : chatState === "error" ? "error" : "succeeded"} />
              </div>

              {/* Error */}
              {chatState === "error" && chatError && (
                chatErrorCode === "SQL_GUARDRAIL_BLOCKED" ? (
                  <div className="answer-blocked">
                    <div className="blocked-icon">⊘</div>
                    <div className="blocked-body">
                      <p className="blocked-title">Query blocked — data modifications are not permitted</p>
                      <p className="blocked-desc">
                        ChatBI is a read-only analytics platform. Requests to insert, update, delete,
                        or otherwise modify data are automatically rejected by the security guardrail.
                        If you have a legitimate data correction request, contact your data team directly.
                      </p>
                    </div>
                  </div>
                ) : chatErrorCode === "VALIDATION_ERROR" ? (
                  <div className="answer-blocked answer-blocked--warn">
                    <div className="blocked-icon">⚠</div>
                    <div className="blocked-body">
                      <p className="blocked-title">Request rejected — invalid query format</p>
                      <p className="blocked-desc">{chatError}</p>
                    </div>
                  </div>
                ) : (
                  <div className="answer-error">
                    {chatErrorCode && <span className="answer-error-code">{chatErrorCode}</span>}
                    {chatError}
                  </div>
                )
              )}

              {/* Loading skeleton */}
              {chatState === "loading" && (
                <div className="loading-area">
                  <div className="skeleton-line long" />
                  <div className="skeleton-line medium" />
                  <div className="skeleton-line short" />
                </div>
              )}

              {/* Answer text */}
              {answer && chatState !== "loading" && (
                <p className="answer-text">{answer}</p>
              )}

              {/* Warnings */}
              {warnings.length > 0 && (
                <div className="warnings-row">
                  {warnings.map((w, i) => (
                    <span className="warning-chip" key={i}>{warningText(w)}</span>
                  ))}
                </div>
              )}

              {/* Chart */}
              <ChartPanel spec={chart} rows={rows} />

              {/* Data table */}
              <DataTable rows={rows} />

              {/* Evidence */}
              <EvidenceSection items={citations} />

              {/* Agent timeline */}
              <AgentTimeline items={timeline} open={timelineOpen} onToggle={() => setTimelineOpen(!timelineOpen)} />
            </div>
          )}
          </div>
          )}
        </main>
      </div>

      {/* ── Developer drawer ── */}
      <div className="dev-drawer">
        <button
          className="dev-toggle"
          type="button"
          onClick={() => setDevOpen(!devOpen)}
        >
          <span>Developer tools</span>
          <span className="toggle-arrow">{devOpen ? "▾" : "▸"}</span>
        </button>
        {devOpen && (
          <div className="dev-content">
            <div className="dev-cols">
              <div>
                <p className="dev-section-label">Last query trace</p>
                <pre className="dev-pre">{chatResponse ? JSON.stringify(chatResponse, null, 2) : "Run a query first."}</pre>
              </div>
              <div>
                <p className="dev-section-label">
                  Admin summary
                  {adminState === "loading" && <span className="dev-loading"> loading…</span>}
                </p>
                <pre className="dev-pre">{adminPayload ? JSON.stringify(adminPayload, null, 2) : "Load admin summary first."}</pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
