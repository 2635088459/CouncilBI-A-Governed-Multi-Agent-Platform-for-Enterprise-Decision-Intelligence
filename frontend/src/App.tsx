import { ChangeEvent, FormEvent, ReactElement, ReactNode, useEffect, useRef, useState } from "react";

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
    table_result_source?: string | null;
  };
  warnings?: WarningItem[];
  error?: ApiError | null;
};

// Spec FV10.4 FR-FV10-054: one entry per turn in the current session's
// continuous thread (question + its answer), appended rather than
// replacing the previous turn.
type ChatTurn = {
  id: string;
  question: string;
  state: ApiState;
  response?: ChatResponse;
  errorCode: string;
  error: string;
};

// One row from GET /api/v2/chat/history — a lightweight summary of a past
// turn (not the full original answer envelope: no table_result/chart_spec/
// evidence_list/agent_timeline, those aren't persisted for replay here).
type HistoryItem = {
  trace_id?: string;
  session_id?: string;
  question?: string;
  answer_text?: string;
  sql_text?: string;
  status?: string;
  error_code?: string;
  created_at?: string;
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

type UploadedFile = {
  file_id: string;
  original_name: string;
  file_type?: string;
  mime_type?: string;
  size_bytes?: number;
  status: string; // processing | schema_ready | indexing | ready | failed
  error_reason?: string | null;
  row_count?: number | null;
  promoted_to_doc_id?: string | null;
  created_at: string;
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

async function uploadFile(file: File, token: string): Promise<{ data?: { file_id?: string }; error?: ApiError | null }> {
  const form = new FormData();
  form.append("file", file);
  form.append("scope", "user");
  const resp = await fetch(apiUrl("/api/v2/files/upload"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "X-Request-Id": requestIdStr() },
    body: form,
  });
  const payload = (await resp.json().catch(() => ({}))) as { data?: { file_id?: string }; error?: ApiError | null };
  if (!resp.ok) {
    throw new Error(payload.error?.message ?? `HTTP ${resp.status}`);
  }
  return payload;
}

async function deleteFile(fileId: string, token: string): Promise<void> {
  await fetch(apiUrl(`/api/v2/files/${fileId}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}`, "X-Request-Id": requestIdStr() },
  });
}

function fmtBytes(n?: number): string {
  if (!n) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fileStatusLabel(status: string): string {
  if (status === "ready") return "Ready";
  if (status === "failed") return "Failed";
  return "Processing…";
}

function fileStatusBadgeClass(status: string): string {
  if (status === "ready") return "badge-ok";
  if (status === "failed") return "badge-err";
  return "badge-neu";
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

// LLM-synthesized answer_text arrives as markdown (bold, bullet/numbered
// lists, occasional headers) — rendered as a bare string it shows literal
// "**text**" and loses all line breaks (a <p> collapses whitespace). This is
// a small hand-rolled renderer rather than a dependency: the answer shape
// this app actually produces is narrow (paragraphs, lists, bold/code spans).
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(<strong key={`${keyPrefix}-b-${i++}`}>{token.slice(2, -2)}</strong>);
    } else {
      parts.push(<code key={`${keyPrefix}-c-${i++}`}>{token.slice(1, -1)}</code>);
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

function renderMarkdown(text: string, className = "answer-text"): ReactElement {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let paraBuffer: string[] = [];
  let listBuffer: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let blockKey = 0;

  function flushPara() {
    const joined = paraBuffer.join(" ").trim();
    if (joined) blocks.push(<p key={`p-${blockKey++}`}>{renderInline(joined, `p-${blockKey}`)}</p>);
    paraBuffer = [];
  }
  function flushList() {
    if (!listBuffer.length) return;
    const items = listBuffer.map((item, idx) => (
      <li key={`li-${blockKey}-${idx}`}>{renderInline(item, `li-${blockKey}-${idx}`)}</li>
    ));
    blocks.push(
      listType === "ol" ? <ol key={`list-${blockKey++}`}>{items}</ol> : <ul key={`list-${blockKey++}`}>{items}</ul>
    );
    listBuffer = [];
    listType = null;
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushPara();
      flushList();
      continue;
    }
    const headerMatch = line.match(/^#{1,6}\s+(.*)/);
    const bulletMatch = line.match(/^[-*]\s+(.*)/);
    const numberedMatch = line.match(/^\d+\.\s+(.*)/);
    if (headerMatch) {
      flushPara();
      flushList();
      blocks.push(
        <p key={`h-${blockKey++}`} className="answer-heading">{renderInline(headerMatch[1], `h-${blockKey}`)}</p>
      );
    } else if (bulletMatch) {
      flushPara();
      if (listType !== "ul") flushList();
      listType = "ul";
      listBuffer.push(bulletMatch[1]);
    } else if (numberedMatch) {
      flushPara();
      if (listType !== "ol") flushList();
      listType = "ol";
      listBuffer.push(numberedMatch[1]);
    } else {
      flushList();
      paraBuffer.push(line);
    }
  }
  flushPara();
  flushList();

  return <div className={className}>{blocks}</div>;
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

// ─── Files Panel ──────────────────────────────────────────────────────────────

function FilesPanel({
  token,
  selectedFileIds,
  onToggleFile,
}: {
  token: string;
  selectedFileIds: string[];
  onToggleFile: (fileId: string) => void;
}) {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [uploadState, setUploadState] = useState<ApiState>("idle");
  const [uploadError, setUploadError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    try {
      const resp = await getJson<{ data?: { files?: UploadedFile[] } }>("/api/v2/files", token);
      setFiles(resp.data?.files ?? []);
    } catch {
      // keep the last-known list on a transient refresh failure
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const hasPending = files.some((f) => f.status !== "ready" && f.status !== "failed");
    if (!hasPending) return;
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadState("loading");
    setUploadError("");
    try {
      await uploadFile(file, token);
      await refresh();
      setUploadState("success");
    } catch (err) {
      setUploadState("error");
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleDelete(fileId: string) {
    await deleteFile(fileId, token);
    await refresh();
  }

  return (
    <div className="sidebar-block">
      <p className="sidebar-label">My files</p>
      <input
        ref={inputRef}
        type="file"
        id="file-upload-input"
        className="file-input-hidden"
        accept=".csv,.xlsx,.xls,.pdf,.docx,.pptx,.txt"
        onChange={handleFileChange}
      />
      <label htmlFor="file-upload-input" className="sidebar-admin-btn file-upload-btn">
        {uploadState === "loading" ? "Uploading…" : "+ Upload file"}
      </label>
      {uploadState === "error" && <p className="form-error">{uploadError}</p>}
      {files.length === 0 ? (
        <p className="sidebar-hint">No files uploaded yet.</p>
      ) : (
        <div className="file-list">
          {files.map((f) => (
            <div className="file-item" key={f.file_id}>
              <label className="file-item-main">
                <input
                  type="checkbox"
                  disabled={f.status !== "ready"}
                  checked={selectedFileIds.includes(f.file_id)}
                  onChange={() => onToggleFile(f.file_id)}
                />
                <span className="file-item-name" title={f.original_name}>{f.original_name}</span>
              </label>
              <div className="file-item-meta">
                <span className={`status-badge ${fileStatusBadgeClass(f.status)}`}>{fileStatusLabel(f.status)}</span>
                <span className="file-item-size">{fmtBytes(f.size_bytes)}</span>
                <button
                  type="button"
                  className="file-item-delete"
                  onClick={() => handleDelete(f.file_id)}
                  aria-label={`Delete ${f.original_name}`}
                >
                  ×
                </button>
              </div>
              {f.status === "failed" && f.error_reason && (
                <p className="file-item-error">{f.error_reason}</p>
              )}
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
  const [loadState, setLoadState] = useState<ApiState>("loading");
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

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
                                {renderMarkdown(r.answer_text, "audit-detail-answer")}
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

// ─── Admin Files Review ───────────────────────────────────────────────────────

type AdminFileRecord = UploadedFile & { user_id: string };

function AdminFilesPanel({ token }: { token: string }) {
  const [records, setRecords] = useState<AdminFileRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loadState, setLoadState] = useState<ApiState>("loading");
  const [filterUser, setFilterUser] = useState("");
  const [filterStatus, setFilterStatus] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [filterName, setFilterName] = useState("");
  const [page, setPage] = useState(0);
  const [actionError, setActionError] = useState("");
  const [pendingFileId, setPendingFileId] = useState("");
  const pageSize = 20;

  async function load(pg = 0) {
    setLoadState("loading");
    setActionError("");
    try {
      const params = new URLSearchParams();
      if (filterUser.trim()) params.set("user_id", filterUser.trim());
      if (filterStatus !== "all") params.set("status", filterStatus);
      if (filterType !== "all") params.set("file_type", filterType);
      if (filterName.trim()) params.set("q", filterName.trim());
      params.set("limit", String(pageSize));
      params.set("offset", String(pg * pageSize));
      const resp = await getJson<{ data: { files: AdminFileRecord[]; total: number } }>(
        `/api/v2/admin/files?${params}`, token
      );
      setRecords(resp?.data?.files ?? []);
      setTotal(resp?.data?.total ?? 0);
      setPage(pg);
      setLoadState("success");
    } catch {
      setLoadState("error");
    }
  }

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handlePromote(fileId: string) {
    setPendingFileId(fileId);
    setActionError("");
    try {
      await postJson("/api/v2/admin/knowledge/promote-file", { file_id: fileId }, token);
      await load(page);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setPendingFileId("");
    }
  }

  async function handleDemote(docId: string) {
    setPendingFileId(docId);
    setActionError("");
    try {
      const resp = await fetch(apiUrl(`/api/v2/admin/knowledge/${docId}?mode=demote`), {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}`, "X-Request-Id": requestIdStr() },
      });
      if (!resp.ok) {
        const payload = (await resp.json().catch(() => ({}))) as { error?: ApiError };
        throw new Error(payload.error?.message ?? `HTTP ${resp.status}`);
      }
      await load(page);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setPendingFileId("");
    }
  }

  function fmtTime(iso: string) {
    const d = new Date(iso);
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="admin-dashboard">
      <div className="audit-filter-bar">
        <input
          className="audit-filter-input"
          placeholder="Filter by uploader…"
          value={filterUser}
          onChange={(e) => setFilterUser(e.target.value)}
        />
        <input
          className="audit-filter-input"
          placeholder="Search filename…"
          value={filterName}
          onChange={(e) => setFilterName(e.target.value)}
        />
        <select className="audit-filter-select" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
          <option value="all">All status</option>
          <option value="ready">Ready</option>
          <option value="processing">Processing</option>
          <option value="failed">Failed</option>
        </select>
        <select className="audit-filter-select" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
          <option value="all">All types</option>
          <option value="structured">Structured</option>
          <option value="unstructured">Unstructured</option>
        </select>
        <button className="audit-load-btn" onClick={() => load(0)} disabled={loadState === "loading"}>
          {loadState === "loading" ? "Loading…" : "Load"}
        </button>
      </div>

      {actionError && <p className="form-error">{actionError}</p>}

      {loadState === "idle" && (
        <div className="audit-empty">Click <strong>Load</strong> to view uploaded files across the org.</div>
      )}
      {loadState === "success" && records.length === 0 && (
        <div className="audit-empty">No files found.</div>
      )}
      {records.length > 0 && (
        <>
          <div className="audit-table-wrap">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>Uploaded</th>
                  <th>Uploader</th>
                  <th>File</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Knowledge Base</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {records.map((f) => {
                  const canPromote = f.file_type === "unstructured" && f.status === "ready" && !f.promoted_to_doc_id;
                  const canDemote = Boolean(f.promoted_to_doc_id);
                  const isPending = pendingFileId === f.file_id || pendingFileId === f.promoted_to_doc_id;
                  return (
                    <tr key={f.file_id}>
                      <td className="audit-cell-time">{fmtTime(f.created_at)}</td>
                      <td className="audit-cell-user" title={f.user_id}>{f.user_id}</td>
                      <td className="audit-cell-question" title={f.original_name}>{f.original_name}</td>
                      <td>{f.file_type}</td>
                      <td>
                        <span className={`status-badge ${fileStatusBadgeClass(f.status)}`}>{fileStatusLabel(f.status)}</span>
                      </td>
                      <td>{fmtBytes(f.size_bytes)}</td>
                      <td>{f.promoted_to_doc_id ? "Promoted" : "—"}</td>
                      <td>
                        {canPromote && (
                          <button
                            type="button"
                            className="sidebar-admin-btn"
                            disabled={isPending}
                            onClick={() => handlePromote(f.file_id)}
                          >
                            {isPending ? "…" : "Promote"}
                          </button>
                        )}
                        {canDemote && (
                          <button
                            type="button"
                            className="sidebar-admin-btn"
                            disabled={isPending}
                            onClick={() => handleDemote(f.promoted_to_doc_id as string)}
                          >
                            {isPending ? "…" : "Demote"}
                          </button>
                        )}
                        {!canPromote && !canDemote && "—"}
                      </td>
                    </tr>
                  );
                })}
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

// One turn (question + its answer) within the current session's continuous
// thread (FR-FV10-054). Pulled out of App's render so the thread can just
// `.map()` this per turn instead of repeating the whole answer layout.
function ChatTurnCard({
  turn,
  timelineOpen,
  onToggleTimeline,
}: {
  turn: ChatTurn;
  timelineOpen: boolean;
  onToggleTimeline: () => void;
}) {
  const { state, response, errorCode, error, question } = turn;
  const answer = resolveAnswer(response);
  const rows = resolveRows(response);
  const citations = resolveCitations(response);
  const chart = resolveChart(response);
  const timeline = resolveTimeline(response);
  const warnings = response?.warnings ?? [];
  const traceId = response?.trace_id;

  return (
    <div className="answer-area">
      <p className="turn-question">{question}</p>
      {/* Header bar */}
      <div className={`answer-header ${state}`}>
        <div className="answer-header-left">
          <span className="answer-label">Answer</span>
          {response?.data?.table_result_source === "file" && (
            <span className="file-source-chip">📎 File data</span>
          )}
          {traceId && <code className="trace-chip">{traceId}</code>}
        </div>
        <StatusBadge status={state === "loading" ? "running" : state === "error" ? "error" : "succeeded"} />
      </div>

      {/* Error */}
      {state === "error" && error && (
        errorCode === "SQL_GUARDRAIL_BLOCKED" ? (
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
        ) : errorCode === "SQL_NOT_QUERYABLE" ? (
          <div className="answer-blocked answer-blocked--warn">
            <div className="blocked-icon">⚠</div>
            <div className="blocked-body">
              <p className="blocked-title">Can't generate a query for this question</p>
              <p className="blocked-desc">
                This question doesn't match a read-only query we can run against the
                available data. Try rephrasing it as a specific data question, or
                check that the data you're asking about exists in a connected table.
              </p>
            </div>
          </div>
        ) : errorCode === "VALIDATION_ERROR" ? (
          <div className="answer-blocked answer-blocked--warn">
            <div className="blocked-icon">⚠</div>
            <div className="blocked-body">
              <p className="blocked-title">Request rejected — invalid query format</p>
              <p className="blocked-desc">{error}</p>
            </div>
          </div>
        ) : errorCode === "REQ_INVALID_ARGUMENT" ? (
          <div className="answer-blocked answer-blocked--warn">
            <div className="blocked-icon">⚠</div>
            <div className="blocked-body">
              <p className="blocked-title">Can't answer this with the selected file(s)</p>
              <p className="blocked-desc">{error}</p>
            </div>
          </div>
        ) : (
          <div className="answer-error">
            {errorCode && <span className="answer-error-code">{errorCode}</span>}
            {error}
          </div>
        )
      )}

      {/* Loading skeleton */}
      {state === "loading" && (
        <div className="loading-area">
          <div className="skeleton-line long" />
          <div className="skeleton-line medium" />
          <div className="skeleton-line short" />
        </div>
      )}

      {/* Answer text */}
      {answer && state !== "loading" && renderMarkdown(answer)}

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
      <AgentTimeline items={timeline} open={timelineOpen} onToggle={onToggleTimeline} />
    </div>
  );
}

type HistorySessionGroup = {
  sessionId: string;
  firstQuestion: string;
  turnCount: number;
  earliestAt: string;
  latestAt: string;
  hasFailure: boolean;
};

function groupHistoryBySession(items: HistoryItem[]): HistorySessionGroup[] {
  const groups = new Map<string, HistorySessionGroup>();
  for (const item of items) {
    const sessionId = item.session_id;
    if (!sessionId) continue;
    const createdAt = item.created_at ?? "";
    const existing = groups.get(sessionId);
    if (!existing) {
      groups.set(sessionId, {
        sessionId,
        firstQuestion: item.question ?? "(no question)",
        turnCount: 1,
        earliestAt: createdAt,
        latestAt: createdAt,
        hasFailure: item.status === "failed",
      });
      continue;
    }
    existing.turnCount += 1;
    existing.hasFailure = existing.hasFailure || item.status === "failed";
    if (createdAt > existing.latestAt) existing.latestAt = createdAt;
    if (createdAt && (!existing.earliestAt || createdAt < existing.earliestAt)) {
      existing.earliestAt = createdAt;
      existing.firstQuestion = item.question ?? existing.firstQuestion;
    }
  }
  return Array.from(groups.values()).sort((a, b) => (a.latestAt < b.latestAt ? 1 : -1));
}

// FR-FV10-054's own note: "the previous session's history remains queryable
// via the existing chat-history endpoint" — that endpoint existed, but
// nothing in the UI ever called it. This panel is the missing surface.
function HistoryPanel({
  state,
  items,
  activeSessionId,
  onClose,
  onResume,
}: {
  state: ApiState;
  items: HistoryItem[];
  activeSessionId: string;
  onClose: () => void;
  onResume: (sessionId: string) => void;
}) {
  const sessions = groupHistoryBySession(items);
  return (
    <div className="history-overlay" onClick={onClose}>
      <div className="history-panel" onClick={(e) => e.stopPropagation()}>
        <div className="history-panel-header">
          <p className="history-panel-title">Chat history</p>
          <button className="history-close-btn" type="button" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="history-panel-body">
          {state === "loading" && <p className="history-empty">Loading…</p>}
          {state === "error" && <p className="history-empty">Couldn't load history. Try again.</p>}
          {state === "success" && sessions.length === 0 && (
            <p className="history-empty">No past sessions yet.</p>
          )}
          {sessions.map((session) => (
            <button
              key={session.sessionId}
              type="button"
              className={`history-session-row ${session.sessionId === activeSessionId ? "active" : ""}`}
              onClick={() => onResume(session.sessionId)}
            >
              <p className="history-session-question">{session.firstQuestion}</p>
              <p className="history-session-meta">
                <code>{session.sessionId}</code>
                <span>{session.turnCount} turn{session.turnCount > 1 ? "s" : ""}</span>
                {session.hasFailure && <span className="history-session-failed">had errors</span>}
              </p>
            </button>
          ))}
        </div>
      </div>
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
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [devOpen, setDevOpen] = useState(false);
  const [adminPayload, setAdminPayload] = useState<unknown>(null);
  const [adminState, setAdminState] = useState<ApiState>("idle");
  const [activeTab, setActiveTab] = useState<"chat" | "admin" | "files">("chat");
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyState, setHistoryState] = useState<ApiState>("idle");
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);

  const [sessionId, setSessionId] = useState(newSessionId());
  const isAdmin = role === "admin";

  const isLoggedIn = Boolean(token);
  const lastTurn = messages[messages.length - 1];
  const chatState: ApiState = lastTurn?.state ?? "idle";

  function handleLoginSuccess(newToken: string, email: string) {
    setToken(newToken);
    setUserEmail(email);
  }

  function handleLogout() {
    setToken("");
    setUserEmail("");
    setMessages([]);
  }

  // FR-FV10-054 / design §7: a fresh session_id and a visually empty thread —
  // the previous session's history is not deleted, just no longer shown.
  // File selection is scoped to "this session" (design §7), so it clears
  // too: the backend has no active file_ids for a session_id it has never
  // seen, and leaving the checkboxes ticked would visually lie about that.
  function startNewChat() {
    setSessionId(newSessionId());
    setMessages([]);
    setSelectedFileIds([]);
  }

  async function openHistory() {
    setHistoryOpen(true);
    setHistoryState("loading");
    try {
      const payload = await getJson<{ data?: { items?: HistoryItem[] } }>(
        `/api/v2/chat/history?user_id=${encodeURIComponent(userEmail)}`,
        token
      );
      setHistoryItems(payload.data?.items ?? []);
      setHistoryState("success");
    } catch {
      setHistoryState("error");
    }
  }

  // A history item is a lightweight summary (question/answer_text/status),
  // not the full original response envelope — table/chart/evidence/timeline
  // are not persisted for replay, so a resumed turn just won't show them.
  // Resuming still switches the active session_id, so new follow-up
  // questions land in the same backend session (file-attachment stickiness
  // and conversation context both key off session_id, per FR-FV10-055/052).
  function resumeHistorySession(targetSessionId: string) {
    const sessionTurns = historyItems
      .filter((item) => item.session_id === targetSessionId)
      .slice()
      .reverse()
      .map((item): ChatTurn => ({
        id: item.trace_id ?? requestIdStr(),
        question: item.question ?? "",
        state: item.status === "failed" ? "error" : "success",
        errorCode: item.error_code ?? "",
        error: item.status === "failed" ? item.error_code ?? "This question failed." : "",
        response: {
          trace_id: item.trace_id,
          data: { answer_text: item.answer_text, sql: item.sql_text },
        },
      }));
    setSessionId(targetSessionId);
    setMessages(sessionTurns);
    setSelectedFileIds([]);
    setHistoryOpen(false);
  }

  function toggleFileSelection(fileId: string) {
    setSelectedFileIds((prev) =>
      prev.includes(fileId) ? prev.filter((id) => id !== fileId) : [...prev, fileId]
    );
  }

  async function submitQuestion(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    const turnId = requestIdStr();
    const askedQuestion = question;
    setMessages((prev) => [
      ...prev,
      { id: turnId, question: askedQuestion, state: "loading", errorCode: "", error: "" },
    ]);
    try {
      const payload = await postJson<ChatResponse>(
        "/api/v2/chat/query",
        {
          request_id: requestIdStr(),
          user_id: userEmail || "frontend-user",
          session_id: sessionId,
          question: askedQuestion,
          locale,
          role,
          file_ids: selectedFileIds,
        },
        token
      );
      const nextState: ApiState = payload.error ? "error" : "success";
      const nextErrorCode = payload.error?.code ?? "";
      const nextError = payload.error ? payload.error.message ?? payload.error.code ?? "An error occurred." : "";
      setMessages((prev) =>
        prev.map((turn) =>
          turn.id === turnId
            ? { ...turn, state: nextState, response: payload, errorCode: nextErrorCode, error: nextError }
            : turn
        )
      );
    } catch (err) {
      const e = err as Error & { errorCode?: string };
      setMessages((prev) =>
        prev.map((turn) =>
          turn.id === turnId
            ? { ...turn, state: "error", errorCode: e.errorCode ?? "", error: e.message || String(err) }
            : turn
        )
      );
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
          <div className="sidebar-block sidebar-block-row">
            <button
              className="new-chat-btn"
              type="button"
              onClick={startNewChat}
              disabled={messages.length === 0}
              title="Start a new session — this session's history stays available in chat history."
            >
              + New chat
            </button>
            <button
              className="history-btn"
              type="button"
              onClick={openHistory}
              title="Browse past sessions and resume one."
            >
              History
            </button>
          </div>
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
          <FilesPanel token={token} selectedFileIds={selectedFileIds} onToggleFile={toggleFileSelection} />
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
              <button
                className={`tab-btn ${activeTab === "files" ? "active" : ""}`}
                type="button"
                onClick={() => setActiveTab("files")}
              >
                Files Review
              </button>
            </div>
          )}

          {/* Admin dashboard */}
          {activeTab === "admin" && isAdmin && (
            <AdminDashboard token={token} />
          )}

          {/* Admin files review */}
          {activeTab === "files" && isAdmin && (
            <AdminFilesPanel token={token} />
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
            <p className="question-hint">
              ⌘ Enter to run · Role: <strong>{role}</strong>
              {selectedFileIds.length > 0 && (
                <span className="attached-files-chip">📎 {selectedFileIds.length} file{selectedFileIds.length > 1 ? "s" : ""} attached</span>
              )}
            </p>
          </form>

          {/* Conversation thread — every turn in this session, appended (FR-FV10-054) */}
          {messages.length > 0 && (
            <div className="chat-thread">
              {messages.map((turn) => (
                <ChatTurnCard
                  key={turn.id}
                  turn={turn}
                  timelineOpen={timelineOpen}
                  onToggleTimeline={() => setTimelineOpen(!timelineOpen)}
                />
              ))}
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
                <pre className="dev-pre">{lastTurn?.response ? JSON.stringify(lastTurn.response, null, 2) : "Run a query first."}</pre>
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

      {historyOpen && (
        <HistoryPanel
          state={historyState}
          items={historyItems}
          activeSessionId={sessionId}
          onClose={() => setHistoryOpen(false)}
          onResume={resumeHistorySession}
        />
      )}
    </div>
  );
}
