import { useState, useEffect, useCallback, useRef } from "react";
import {
  listJobs,
  submitJob,
  cancelJob,
  type BackgroundJob,
  type JobListResponse,
  type JobType,
  type JobStatus,
} from "../api/backgroundJobs";

/* ------------------------------------------------------------------ */
/* Constants                                                            */
/* ------------------------------------------------------------------ */

const JOB_TYPES: { type: JobType; label: string; description: string; icon: string }[] = [
  {
    type: "ANALYZE_TRANSACTIONS",
    label: "Analyse Transactions",
    description: "Compute income/expense statistics across all accounts",
    icon: "📊",
  },
  {
    type: "GENERATE_INSIGHTS",
    label: "Generate Insights",
    description: "Run proactive financial intelligence engine",
    icon: "💡",
  },
  {
    type: "PORTFOLIO_RECALCULATION",
    label: "Recalculate Portfolio",
    description: "Recalculate net balances across all currencies",
    icon: "💼",
  },
  {
    type: "DOCUMENT_REPROCESS",
    label: "Reprocess Document",
    description: "Re-parse and re-import a financial document",
    icon: "📄",
  },
];

const STATUS_COLORS: Record<JobStatus, string> = {
  QUEUED: "#6c7ee0",
  RUNNING: "#f59e0b",
  COMPLETED: "#10b981",
  FAILED: "#ef4444",
  CANCELLED: "#6b7280",
};

const STATUS_ICONS: Record<JobStatus, string> = {
  QUEUED: "⏳",
  RUNNING: "⚙️",
  COMPLETED: "✅",
  FAILED: "❌",
  CANCELLED: "🚫",
};

const POLL_INTERVAL_MS = 3000;

/* ------------------------------------------------------------------ */
/* Utility helpers                                                      */
/* ------------------------------------------------------------------ */

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const s = new Date(start);
  const e = end ? new Date(end) : new Date();
  const ms = e.getTime() - s.getTime();
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ${secs % 60}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/* ------------------------------------------------------------------ */
/* Progress bar                                                         */
/* ------------------------------------------------------------------ */

function ProgressBar({ pct, status }: { pct: number; status: JobStatus }) {
  const color = STATUS_COLORS[status];
  return (
    <div
      style={{
        background: "rgba(255,255,255,0.08)",
        borderRadius: "8px",
        overflow: "hidden",
        height: "8px",
        width: "100%",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${pct}%`,
          background: `linear-gradient(90deg, ${color}88, ${color})`,
          borderRadius: "8px",
          transition: "width 0.5s ease",
          boxShadow: status === "RUNNING" ? `0 0 8px ${color}` : "none",
        }}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Status badge                                                         */
/* ------------------------------------------------------------------ */

function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      style={{
        background: STATUS_COLORS[status] + "22",
        color: STATUS_COLORS[status],
        border: `1px solid ${STATUS_COLORS[status]}44`,
        borderRadius: "20px",
        padding: "2px 10px",
        fontSize: "0.73rem",
        fontWeight: 700,
        letterSpacing: "0.03em",
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        whiteSpace: "nowrap",
      }}
    >
      {STATUS_ICONS[status]} {status}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Navigation helper                                                  */
/* ------------------------------------------------------------------ */

function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/* ------------------------------------------------------------------ */
/* Money & Number formatting helpers                                  */
/* ------------------------------------------------------------------ */

function formatMoney(amount: number | null | undefined, currency?: string): string {
  if (typeof amount !== "number" || isNaN(amount)) {
    return "—";
  }
  const formatted = amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${currency} ${formatted}` : formatted;
}

function formatSignedMoney(amount: number | null | undefined, currency?: string): string {
  if (typeof amount !== "number" || isNaN(amount)) {
    return "—";
  }
  const prefix = amount > 0 ? "+" : "";
  const formatted = amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${prefix}${currency} ${formatted}` : `${prefix}${formatted}`;
}

/* ------------------------------------------------------------------ */
/* Insights result types & helpers                                    */
/* ------------------------------------------------------------------ */

interface InsightSummaryItem {
  id?: string;
  insight_type?: string;
  severity?: string;
  title?: string;
  description?: string;
  currency?: string;
  metric?: string;
  change_amount?: number;
  change_percent?: number | null;
  confidence?: string;
}

interface GenerateInsightsPayload {
  insights_generated?: number;
  data_sufficient?: boolean;
  data_sufficiency_reason?: string | null;
  currencies_evaluated?: string[];
  insights_summary: InsightSummaryItem[];
}

function parseGenerateInsightsPayload(
  payload: Record<string, unknown> | null | undefined
): GenerateInsightsPayload | null {
  if (!payload || typeof payload !== "object") return null;

  const rawSummary = payload.insights_summary;
  if (!Array.isArray(rawSummary)) return null;

  const summaryItems: InsightSummaryItem[] = [];
  for (const item of rawSummary) {
    if (item && typeof item === "object") {
      const rec = item as Record<string, unknown>;
      summaryItems.push({
        id: typeof rec.id === "string" ? rec.id : undefined,
        insight_type: typeof rec.insight_type === "string" ? rec.insight_type : undefined,
        severity: typeof rec.severity === "string" ? rec.severity : undefined,
        title: typeof rec.title === "string" ? rec.title : undefined,
        description: typeof rec.description === "string" ? rec.description : undefined,
        currency: typeof rec.currency === "string" ? rec.currency : undefined,
        metric: typeof rec.metric === "string" ? rec.metric : undefined,
        change_amount: typeof rec.change_amount === "number" ? rec.change_amount : undefined,
        change_percent: typeof rec.change_percent === "number" ? rec.change_percent : null,
        confidence: typeof rec.confidence === "string" ? rec.confidence : undefined,
      });
    }
  }

  const currenciesEvaluated = Array.isArray(payload.currencies_evaluated)
    ? payload.currencies_evaluated.filter((c): c is string => typeof c === "string")
    : undefined;

  return {
    insights_generated:
      typeof payload.insights_generated === "number"
        ? payload.insights_generated
        : summaryItems.length,
    data_sufficient:
      typeof payload.data_sufficient === "boolean" ? payload.data_sufficient : undefined,
    data_sufficiency_reason:
      typeof payload.data_sufficiency_reason === "string"
        ? payload.data_sufficiency_reason
        : null,
    currencies_evaluated: currenciesEvaluated,
    insights_summary: summaryItems,
  };
}

/* ------------------------------------------------------------------ */
/* ANALYZE_TRANSACTIONS types & parser                                */
/* ------------------------------------------------------------------ */

interface TransactionCurrencySummary {
  currency?: string;
  count?: number;
  total_income?: number;
  total_expense?: number;
  net?: number;
}

interface AnalyzeTransactionsPayload {
  accounts_analysed?: number;
  transaction_count?: number;
  summary: TransactionCurrencySummary[];
}

function parseAnalyzeTransactionsPayload(
  payload: Record<string, unknown> | null | undefined
): AnalyzeTransactionsPayload | null {
  if (!payload || typeof payload !== "object") return null;

  const rawSummary = payload.summary;
  if (!Array.isArray(rawSummary)) return null;

  const summaryItems: TransactionCurrencySummary[] = [];
  for (const item of rawSummary) {
    if (item && typeof item === "object") {
      const rec = item as Record<string, unknown>;
      summaryItems.push({
        currency: typeof rec.currency === "string" ? rec.currency : undefined,
        count: typeof rec.count === "number" ? rec.count : undefined,
        total_income: typeof rec.total_income === "number" ? rec.total_income : undefined,
        total_expense: typeof rec.total_expense === "number" ? rec.total_expense : undefined,
        net: typeof rec.net === "number" ? rec.net : undefined,
      });
    }
  }

  return {
    accounts_analysed:
      typeof payload.accounts_analysed === "number" ? payload.accounts_analysed : undefined,
    transaction_count:
      typeof payload.transaction_count === "number" ? payload.transaction_count : undefined,
    summary: summaryItems,
  };
}

/* ------------------------------------------------------------------ */
/* PORTFOLIO_RECALCULATION types & parser                             */
/* ------------------------------------------------------------------ */

interface PortfolioRecalculationPayload {
  accounts_count?: number;
  portfolio_by_currency: Array<{ currency: string; balance?: number }>;
}

function parsePortfolioRecalculationPayload(
  payload: Record<string, unknown> | null | undefined
): PortfolioRecalculationPayload | null {
  if (!payload || typeof payload !== "object") return null;

  const rawPortfolio = payload.portfolio_by_currency;
  if (!rawPortfolio || typeof rawPortfolio !== "object" || Array.isArray(rawPortfolio)) {
    return null;
  }

  const entries: Array<{ currency: string; balance?: number }> = [];
  for (const [key, val] of Object.entries(rawPortfolio)) {
    entries.push({
      currency: key,
      balance: typeof val === "number" ? val : undefined,
    });
  }

  return {
    accounts_count:
      typeof payload.accounts_count === "number" ? payload.accounts_count : undefined,
    portfolio_by_currency: entries,
  };
}

/* ------------------------------------------------------------------ */
/* DOCUMENT_REPROCESS types & parser                                  */
/* ------------------------------------------------------------------ */

interface DocumentReprocessPayload {
  document_id?: string;
  filename?: string;
  status?: string;
}

function parseDocumentReprocessPayload(
  payload: Record<string, unknown> | null | undefined
): DocumentReprocessPayload | null {
  if (!payload || typeof payload !== "object") return null;
  if (typeof payload.document_id !== "string" && typeof payload.filename !== "string") {
    return null;
  }
  return {
    document_id: typeof payload.document_id === "string" ? payload.document_id : undefined,
    filename: typeof payload.filename === "string" ? payload.filename : undefined,
    status: typeof payload.status === "string" ? payload.status : undefined,
  };
}

function getSeverityColor(severity?: string): string {
  switch ((severity || "").toUpperCase()) {
    case "HIGH":
    case "CRITICAL":
    case "HIGH_RISK":
      return "#f87171";
    case "MEDIUM":
    case "WARNING":
      return "#fbbf24";
    case "LOW":
    case "INFO":
      return "#38bdf8";
    default:
      return "#94a3b8";
  }
}

function getSeverityBg(severity?: string): string {
  switch ((severity || "").toUpperCase()) {
    case "HIGH":
    case "CRITICAL":
    case "HIGH_RISK":
      return "rgba(239, 68, 68, 0.12)";
    case "MEDIUM":
    case "WARNING":
      return "rgba(245, 158, 11, 0.12)";
    case "LOW":
    case "INFO":
      return "rgba(56, 189, 248, 0.12)";
    default:
      return "rgba(148, 163, 184, 0.12)";
  }
}

function getSeverityBorder(severity?: string): string {
  switch ((severity || "").toUpperCase()) {
    case "HIGH":
    case "CRITICAL":
    case "HIGH_RISK":
      return "rgba(239, 68, 68, 0.3)";
    case "MEDIUM":
    case "WARNING":
      return "rgba(245, 158, 11, 0.3)";
    case "LOW":
    case "INFO":
      return "rgba(56, 189, 248, 0.3)";
    default:
      return "rgba(148, 163, 184, 0.2)";
  }
}

/* ------------------------------------------------------------------ */
/* Job card                                                             */
/* ------------------------------------------------------------------ */

function JobCard({
  job,
  onCancel,
  cancelling,
}: {
  job: BackgroundJob;
  onCancel: (id: string) => void;
  cancelling: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showRawJson, setShowRawJson] = useState(false);
  const typeInfo = JOB_TYPES.find((t) => t.type === job.job_type);
  const canCancel = job.status === "QUEUED" || job.status === "RUNNING";

  const insightsPayload =
    job.job_type === "GENERATE_INSIGHTS" && job.status === "COMPLETED"
      ? parseGenerateInsightsPayload(job.result_payload)
      : null;

  const analyzePayload =
    job.job_type === "ANALYZE_TRANSACTIONS" && job.status === "COMPLETED"
      ? parseAnalyzeTransactionsPayload(job.result_payload)
      : null;

  const portfolioPayload =
    (job.job_type === "PORTFOLIO_RECALCULATION" ||
      (job.job_type as string) === "RECALCULATE_PORTFOLIO") &&
    job.status === "COMPLETED"
      ? parsePortfolioRecalculationPayload(job.result_payload)
      : null;

  const documentPayload =
    job.job_type === "DOCUMENT_REPROCESS" && job.status === "COMPLETED"
      ? parseDocumentReprocessPayload(job.result_payload)
      : null;

  return (
    <div
      id={`job-card-${job.id}`}
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: "16px",
        padding: "18px 20px",
        transition: "box-shadow 0.2s, border-color 0.2s",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = "rgba(108,126,224,0.4)";
        (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 20px rgba(108,126,224,0.1)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.08)";
        (e.currentTarget as HTMLElement).style.boxShadow = "none";
      }}
      onClick={() => setExpanded((x) => !x)}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "12px" }}>
        <span style={{ fontSize: "1.4rem" }}>{typeInfo?.icon ?? "🔧"}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: "0.9rem", color: "#e2e8f0" }}>
            {typeInfo?.label ?? job.job_type}
          </div>
          <div style={{ fontSize: "0.73rem", color: "#94a3b8", marginTop: "2px" }}>
            ID: {job.id.slice(0, 8)}… · Submitted {formatTime(job.created_at)}
          </div>
        </div>
        <StatusBadge status={job.status} />
        {canCancel && (
          <button
            id={`cancel-btn-${job.id}`}
            disabled={cancelling}
            onClick={(e) => {
              e.stopPropagation();
              onCancel(job.id);
            }}
            style={{
              background: "rgba(239,68,68,0.12)",
              border: "1px solid rgba(239,68,68,0.3)",
              color: "#f87171",
              borderRadius: "8px",
              padding: "4px 12px",
              fontSize: "0.75rem",
              cursor: cancelling ? "not-allowed" : "pointer",
              opacity: cancelling ? 0.6 : 1,
              transition: "all 0.2s",
            }}
          >
            {cancelling ? "…" : "Cancel"}
          </button>
        )}
      </div>

      {/* Progress */}
      {(job.status === "QUEUED" || job.status === "RUNNING") && (
        <div style={{ marginBottom: "10px" }}>
          <ProgressBar pct={job.progress_pct} status={job.status} />
          <div
            style={{
              fontSize: "0.72rem",
              color: "#94a3b8",
              marginTop: "5px",
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <span>{job.progress_message ?? "Waiting…"}</span>
            <span>{job.progress_pct}%</span>
          </div>
        </div>
      )}

      {/* Timing row */}
      <div
        style={{
          display: "flex",
          gap: "16px",
          fontSize: "0.72rem",
          color: "#64748b",
          flexWrap: "wrap",
        }}
      >
        {job.started_at && (
          <span>⏱ Duration: {formatDuration(job.started_at, job.completed_at)}</span>
        )}
        {job.completed_at && <span>🏁 Finished: {formatTime(job.completed_at)}</span>}
        {job.status === "RUNNING" && <span className="pulse" style={{ color: "#f59e0b" }}>● Live</span>}
      </div>

      {/* Expandable detail */}
      {expanded && (
        <div
          style={{
            marginTop: "14px",
            paddingTop: "14px",
            borderTop: "1px solid rgba(255,255,255,0.08)",
            fontSize: "0.8rem",
            color: "#94a3b8",
          }}
        >
          {job.error_message && (
            <div
              style={{
                background: "rgba(239,68,68,0.08)",
                border: "1px solid rgba(239,68,68,0.2)",
                borderRadius: "8px",
                padding: "10px 14px",
                color: "#fca5a5",
                marginBottom: "10px",
                fontFamily: "monospace",
                fontSize: "0.75rem",
              }}
            >
              ❌ {job.error_message}
            </div>
          )}
          {job.result_payload && (
            <div>
              {insightsPayload ? (
                /* ── GENERATE_INSIGHTS Result View ── */
                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "10px",
                      flexWrap: "wrap",
                      gap: "8px",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "#cbd5e1" }}>
                      📋 Generated Insights ({insightsPayload.insights_summary.length})
                    </div>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <button
                        type="button"
                        id={`view-analytics-btn-${job.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate("/analytics");
                        }}
                        style={{
                          background: "rgba(99, 102, 241, 0.15)",
                          border: "1px solid rgba(99, 102, 241, 0.4)",
                          color: "#818cf8",
                          borderRadius: "8px",
                          padding: "4px 10px",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          cursor: "pointer",
                          transition: "all 0.2s",
                        }}
                      >
                        📊 View in Analytics
                      </button>
                      <button
                        type="button"
                        id={`toggle-raw-json-btn-${job.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setShowRawJson((prev) => !prev);
                        }}
                        style={{
                          background: showRawJson
                            ? "rgba(255,255,255,0.12)"
                            : "rgba(255,255,255,0.05)",
                          border: "1px solid rgba(255,255,255,0.12)",
                          color: "#94a3b8",
                          borderRadius: "8px",
                          padding: "4px 10px",
                          fontSize: "0.75rem",
                          cursor: "pointer",
                          transition: "all 0.2s",
                        }}
                      >
                        {showRawJson ? "Hide Raw JSON" : "{ } View Raw JSON"}
                      </button>
                    </div>
                  </div>

                  {/* Summary metadata pills */}
                  <div
                    style={{
                      display: "flex",
                      gap: "8px",
                      marginBottom: "12px",
                      flexWrap: "wrap",
                      alignItems: "center",
                    }}
                  >
                    <span
                      style={{
                        background: "rgba(99, 102, 241, 0.15)",
                        border: "1px solid rgba(99, 102, 241, 0.3)",
                        color: "#a5b4fc",
                        borderRadius: "6px",
                        padding: "3px 8px",
                        fontSize: "0.72rem",
                        fontWeight: 600,
                      }}
                    >
                      ✨ {insightsPayload.insights_generated ?? insightsPayload.insights_summary.length} Total Generated
                    </span>

                    {insightsPayload.currencies_evaluated &&
                      insightsPayload.currencies_evaluated.length > 0 && (
                        <span
                          style={{
                            background: "rgba(56, 189, 248, 0.12)",
                            border: "1px solid rgba(56, 189, 248, 0.25)",
                            color: "#7dd3fc",
                            borderRadius: "6px",
                            padding: "3px 8px",
                            fontSize: "0.72rem",
                          }}
                        >
                          💱 Currencies: {insightsPayload.currencies_evaluated.join(", ")}
                        </span>
                      )}

                    {insightsPayload.data_sufficient !== undefined && (
                      <span
                        style={{
                          background: insightsPayload.data_sufficient
                            ? "rgba(16, 185, 129, 0.12)"
                            : "rgba(245, 158, 11, 0.12)",
                          border: `1px solid ${
                            insightsPayload.data_sufficient
                              ? "rgba(16, 185, 129, 0.25)"
                              : "rgba(245, 158, 11, 0.25)"
                          }`,
                          color: insightsPayload.data_sufficient ? "#6ee7b7" : "#fcd34d",
                          borderRadius: "6px",
                          padding: "3px 8px",
                          fontSize: "0.72rem",
                          fontWeight: 600,
                        }}
                      >
                        {insightsPayload.data_sufficient
                          ? "✅ Data Sufficient"
                          : "⚠️ Data Insufficient"}
                      </span>
                    )}
                  </div>

                  {/* Data Sufficiency Reason note */}
                  {insightsPayload.data_sufficiency_reason && (
                    <div
                      style={{
                        background: "rgba(245, 158, 11, 0.08)",
                        border: "1px solid rgba(245, 158, 11, 0.2)",
                        borderRadius: "8px",
                        padding: "8px 12px",
                        color: "#fcd34d",
                        fontSize: "0.75rem",
                        marginBottom: "12px",
                        lineHeight: 1.4,
                      }}
                    >
                      ℹ️ {insightsPayload.data_sufficiency_reason}
                    </div>
                  )}

                  {/* Insight cards list */}
                  {insightsPayload.insights_summary.length === 0 ? (
                    <div
                      style={{
                        background: "rgba(0, 0, 0, 0.2)",
                        border: "1px dashed rgba(255, 255, 255, 0.1)",
                        borderRadius: "8px",
                        padding: "16px",
                        textAlign: "center",
                        color: "#64748b",
                        fontSize: "0.78rem",
                      }}
                    >
                      No actionable insights were produced in this run.
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      {insightsPayload.insights_summary.map((item, idx) => (
                        <div
                          key={item.id ?? `ins-${idx}`}
                          style={{
                            background: "rgba(0, 0, 0, 0.25)",
                            border: "1px solid rgba(255, 255, 255, 0.07)",
                            borderRadius: "10px",
                            padding: "12px 14px",
                            display: "flex",
                            flexDirection: "column",
                            gap: "6px",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              gap: "8px",
                              flexWrap: "wrap",
                            }}
                          >
                            <div
                              style={{
                                fontWeight: 600,
                                color: "#f1f5f9",
                                fontSize: "0.84rem",
                              }}
                            >
                              {item.title || "Financial Insight"}
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              {item.severity && (
                                <span
                                  style={{
                                    fontSize: "0.68rem",
                                    fontWeight: 700,
                                    textTransform: "uppercase",
                                    letterSpacing: "0.05em",
                                    padding: "2px 6px",
                                    borderRadius: "4px",
                                    background: getSeverityBg(item.severity),
                                    color: getSeverityColor(item.severity),
                                    border: `1px solid ${getSeverityBorder(item.severity)}`,
                                  }}
                                >
                                  {item.severity}
                                </span>
                              )}
                              {item.confidence && (
                                <span
                                  style={{
                                    fontSize: "0.68rem",
                                    padding: "2px 6px",
                                    borderRadius: "4px",
                                    background: "rgba(255, 255, 255, 0.06)",
                                    color: "#94a3b8",
                                    border: "1px solid rgba(255, 255, 255, 0.1)",
                                  }}
                                >
                                  Confidence: {item.confidence}
                                </span>
                              )}
                            </div>
                          </div>

                          {item.description && (
                            <p
                              style={{
                                margin: "2px 0 0",
                                color: "#cbd5e1",
                                fontSize: "0.78rem",
                                lineHeight: 1.45,
                              }}
                            >
                              {item.description}
                            </p>
                          )}

                          {/* Meta line */}
                          <div
                            style={{
                              display: "flex",
                              gap: "12px",
                              fontSize: "0.72rem",
                              color: "#64748b",
                              marginTop: "2px",
                              flexWrap: "wrap",
                            }}
                          >
                            {item.metric && (
                              <span>
                                📊 Metric:{" "}
                                <strong style={{ color: "#94a3b8" }}>{item.metric}</strong>
                              </span>
                            )}
                            {item.currency && (
                              <span>
                                💱 Currency:{" "}
                                <strong style={{ color: "#94a3b8" }}>{item.currency}</strong>
                              </span>
                            )}
                            {typeof item.change_amount === "number" && (
                              <span>
                                Amount:{" "}
                                <strong
                                  style={{
                                    color: item.change_amount >= 0 ? "#34d399" : "#f87171",
                                  }}
                                >
                                  {item.currency ? `${item.currency} ` : ""}
                                  {item.change_amount.toLocaleString(undefined, {
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2,
                                  })}
                                </strong>
                              </span>
                            )}
                            {typeof item.change_percent === "number" &&
                              item.change_percent !== null && (
                                <span>
                                  Change:{" "}
                                  <strong
                                    style={{
                                      color:
                                        item.change_percent >= 0 ? "#34d399" : "#f87171",
                                    }}
                                  >
                                    {item.change_percent > 0 ? "+" : ""}
                                    {item.change_percent.toFixed(1)}%
                                  </strong>
                                </span>
                              )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Collapsible raw JSON */}
                  {showRawJson && (
                    <div style={{ marginTop: "12px" }}>
                      <div
                        style={{
                          fontWeight: 600,
                          color: "#64748b",
                          fontSize: "0.72rem",
                          marginBottom: "4px",
                        }}
                      >
                        Raw Payload:
                      </div>
                      <pre
                        style={{
                          background: "rgba(0,0,0,0.3)",
                          borderRadius: "8px",
                          padding: "10px",
                          overflow: "auto",
                          maxHeight: "200px",
                          fontSize: "0.72rem",
                          lineHeight: 1.5,
                          color: "#e2e8f0",
                          margin: 0,
                        }}
                      >
                        {JSON.stringify(job.result_payload, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ) : analyzePayload ? (
                /* ── ANALYZE_TRANSACTIONS Result View ── */
                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "10px",
                      flexWrap: "wrap",
                      gap: "8px",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "#cbd5e1" }}>
                      📊 Transaction Analysis Summary
                    </div>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <button
                        type="button"
                        id={`view-transactions-btn-${job.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate("/transactions");
                        }}
                        style={{
                          background: "rgba(108, 126, 224, 0.15)",
                          border: "1px solid rgba(108, 126, 224, 0.4)",
                          color: "#c7d2fe",
                          borderRadius: "8px",
                          padding: "4px 10px",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          cursor: "pointer",
                          transition: "all 0.2s",
                        }}
                      >
                        💳 View Transactions
                      </button>
                      <button
                        type="button"
                        id={`toggle-raw-json-btn-${job.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setShowRawJson((prev) => !prev);
                        }}
                        style={{
                          background: showRawJson
                            ? "rgba(255,255,255,0.12)"
                            : "rgba(255,255,255,0.05)",
                          border: "1px solid rgba(255,255,255,0.12)",
                          color: "#94a3b8",
                          borderRadius: "8px",
                          padding: "4px 10px",
                          fontSize: "0.75rem",
                          cursor: "pointer",
                          transition: "all 0.2s",
                        }}
                      >
                        {showRawJson ? "Hide Raw JSON" : "{ } View Raw JSON"}
                      </button>
                    </div>
                  </div>

                  {/* Summary badges */}
                  <div
                    style={{
                      display: "flex",
                      gap: "8px",
                      marginBottom: "12px",
                      flexWrap: "wrap",
                      alignItems: "center",
                    }}
                  >
                    <span
                      style={{
                        background: "rgba(108, 126, 224, 0.15)",
                        border: "1px solid rgba(108, 126, 224, 0.3)",
                        color: "#c7d2fe",
                        borderRadius: "6px",
                        padding: "3px 8px",
                        fontSize: "0.72rem",
                        fontWeight: 600,
                      }}
                    >
                      🏦 Accounts Analysed:{" "}
                      {analyzePayload.accounts_analysed !== undefined
                        ? analyzePayload.accounts_analysed
                        : "—"}
                    </span>
                    <span
                      style={{
                        background: "rgba(56, 189, 248, 0.12)",
                        border: "1px solid rgba(56, 189, 248, 0.25)",
                        color: "#7dd3fc",
                        borderRadius: "6px",
                        padding: "3px 8px",
                        fontSize: "0.72rem",
                        fontWeight: 600,
                      }}
                    >
                      📄 Total Transactions:{" "}
                      {analyzePayload.transaction_count !== undefined
                        ? analyzePayload.transaction_count
                        : "—"}
                    </span>
                    <span
                      style={{
                        background: "rgba(255, 255, 255, 0.06)",
                        border: "1px solid rgba(255, 255, 255, 0.1)",
                        color: "#cbd5e1",
                        borderRadius: "6px",
                        padding: "3px 8px",
                        fontSize: "0.72rem",
                      }}
                    >
                      💱 Currencies: {analyzePayload.summary.length}
                    </span>
                  </div>

                  {/* Breakdown by currency */}
                  {analyzePayload.summary.length === 0 ? (
                    <div
                      style={{
                        background: "rgba(0, 0, 0, 0.2)",
                        border: "1px dashed rgba(255, 255, 255, 0.1)",
                        borderRadius: "8px",
                        padding: "16px",
                        textAlign: "center",
                        color: "#64748b",
                        fontSize: "0.78rem",
                      }}
                    >
                      No transactions recorded for the analysed accounts.
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                      {analyzePayload.summary.map((entry, idx) => {
                        const ccy = entry.currency || "Unknown";
                        const isNetPos =
                          typeof entry.net === "number" && entry.net >= 0;
                        const netColor =
                          typeof entry.net === "number"
                            ? isNetPos
                              ? "#34d399"
                              : "#f87171"
                            : "#94a3b8";

                        return (
                          <div
                            key={entry.currency ?? `curr-${idx}`}
                            style={{
                              background: "rgba(0, 0, 0, 0.25)",
                              border: "1px solid rgba(255, 255, 255, 0.07)",
                              borderRadius: "10px",
                              padding: "12px 14px",
                              display: "flex",
                              flexDirection: "column",
                              gap: "8px",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                flexWrap: "wrap",
                                gap: "8px",
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <span
                                  style={{
                                    fontWeight: 700,
                                    fontSize: "0.85rem",
                                    color: "#e2e8f0",
                                    background: "rgba(108, 126, 224, 0.18)",
                                    border: "1px solid rgba(108, 126, 224, 0.35)",
                                    padding: "2px 8px",
                                    borderRadius: "6px",
                                  }}
                                >
                                  {ccy}
                                </span>
                                <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
                                  {entry.count !== undefined
                                    ? `${entry.count} transaction${entry.count !== 1 ? "s" : ""}`
                                    : "Count unavailable"}
                                </span>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                <span style={{ fontSize: "0.72rem", color: "#64748b" }}>
                                  Net Balance:
                                </span>
                                <strong style={{ fontSize: "0.88rem", color: netColor }}>
                                  {formatSignedMoney(entry.net, entry.currency)}
                                </strong>
                              </div>
                            </div>

                            {/* Metrics grid */}
                            <div
                              style={{
                                display: "grid",
                                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                                gap: "8px",
                                marginTop: "2px",
                              }}
                            >
                              <div
                                style={{
                                  background: "rgba(255,255,255,0.03)",
                                  padding: "8px 10px",
                                  borderRadius: "6px",
                                  border: "1px solid rgba(255,255,255,0.04)",
                                }}
                              >
                                <div style={{ fontSize: "0.7rem", color: "#64748b" }}>
                                  Total Income
                                </div>
                                <div
                                  style={{
                                    fontSize: "0.82rem",
                                    fontWeight: 600,
                                    color: "#34d399",
                                    marginTop: "2px",
                                  }}
                                >
                                  {formatMoney(entry.total_income, entry.currency)}
                                </div>
                              </div>
                              <div
                                style={{
                                  background: "rgba(255,255,255,0.03)",
                                  padding: "8px 10px",
                                  borderRadius: "6px",
                                  border: "1px solid rgba(255,255,255,0.04)",
                                }}
                              >
                                <div style={{ fontSize: "0.7rem", color: "#64748b" }}>
                                  Total Expenses
                                </div>
                                <div
                                  style={{
                                    fontSize: "0.82rem",
                                    fontWeight: 600,
                                    color: "#f87171",
                                    marginTop: "2px",
                                  }}
                                >
                                  {formatMoney(entry.total_expense, entry.currency)}
                                </div>
                              </div>
                              <div
                                style={{
                                  background: "rgba(255,255,255,0.03)",
                                  padding: "8px 10px",
                                  borderRadius: "6px",
                                  border: "1px solid rgba(255,255,255,0.04)",
                                }}
                              >
                                <div style={{ fontSize: "0.7rem", color: "#64748b" }}>
                                  Net Result
                                </div>
                                <div
                                  style={{
                                    fontSize: "0.82rem",
                                    fontWeight: 600,
                                    color: netColor,
                                    marginTop: "2px",
                                  }}
                                >
                                  {formatSignedMoney(entry.net, entry.currency)}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Collapsible raw JSON */}
                  {showRawJson && (
                    <div style={{ marginTop: "12px" }}>
                      <div
                        style={{
                          fontWeight: 600,
                          color: "#64748b",
                          fontSize: "0.72rem",
                          marginBottom: "4px",
                        }}
                      >
                        Raw Payload:
                      </div>
                      <pre
                        style={{
                          background: "rgba(0,0,0,0.3)",
                          borderRadius: "8px",
                          padding: "10px",
                          overflow: "auto",
                          maxHeight: "200px",
                          fontSize: "0.72rem",
                          lineHeight: 1.5,
                          color: "#e2e8f0",
                          margin: 0,
                        }}
                      >
                        {JSON.stringify(job.result_payload, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ) : portfolioPayload ? (
                /* ── PORTFOLIO_RECALCULATION Result View ── */
                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "10px",
                      flexWrap: "wrap",
                      gap: "8px",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "#cbd5e1" }}>
                      💼 Portfolio Recalculation Summary
                    </div>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <button
                        type="button"
                        id={`view-accounts-btn-${job.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate("/accounts");
                        }}
                        style={{
                          background: "rgba(16, 185, 129, 0.15)",
                          border: "1px solid rgba(16, 185, 129, 0.4)",
                          color: "#6ee7b7",
                          borderRadius: "8px",
                          padding: "4px 10px",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          cursor: "pointer",
                          transition: "all 0.2s",
                        }}
                      >
                        🏦 View Accounts
                      </button>
                      <button
                        type="button"
                        id={`toggle-raw-json-btn-${job.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setShowRawJson((prev) => !prev);
                        }}
                        style={{
                          background: showRawJson
                            ? "rgba(255,255,255,0.12)"
                            : "rgba(255,255,255,0.05)",
                          border: "1px solid rgba(255,255,255,0.12)",
                          color: "#94a3b8",
                          borderRadius: "8px",
                          padding: "4px 10px",
                          fontSize: "0.75rem",
                          cursor: "pointer",
                          transition: "all 0.2s",
                        }}
                      >
                        {showRawJson ? "Hide Raw JSON" : "{ } View Raw JSON"}
                      </button>
                    </div>
                  </div>

                  {/* Summary badges */}
                  <div
                    style={{
                      display: "flex",
                      gap: "8px",
                      marginBottom: "12px",
                      flexWrap: "wrap",
                      alignItems: "center",
                    }}
                  >
                    <span
                      style={{
                        background: "rgba(16, 185, 129, 0.12)",
                        border: "1px solid rgba(16, 185, 129, 0.25)",
                        color: "#6ee7b7",
                        borderRadius: "6px",
                        padding: "3px 8px",
                        fontSize: "0.72rem",
                        fontWeight: 600,
                      }}
                    >
                      🏦 Accounts Evaluated:{" "}
                      {portfolioPayload.accounts_count !== undefined
                        ? portfolioPayload.accounts_count
                        : "—"}
                    </span>
                    <span
                      style={{
                        background: "rgba(56, 189, 248, 0.12)",
                        border: "1px solid rgba(56, 189, 248, 0.25)",
                        color: "#7dd3fc",
                        borderRadius: "6px",
                        padding: "3px 8px",
                        fontSize: "0.72rem",
                      }}
                    >
                      💱 Active Currencies: {portfolioPayload.portfolio_by_currency.length}
                    </span>
                  </div>

                  {/* Currency Net Balances Grid */}
                  {portfolioPayload.portfolio_by_currency.length === 0 ? (
                    <div
                      style={{
                        background: "rgba(0, 0, 0, 0.2)",
                        border: "1px dashed rgba(255, 255, 255, 0.1)",
                        borderRadius: "8px",
                        padding: "16px",
                        textAlign: "center",
                        color: "#64748b",
                        fontSize: "0.78rem",
                      }}
                    >
                      No portfolio balances found.
                    </div>
                  ) : (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                        gap: "10px",
                      }}
                    >
                      {portfolioPayload.portfolio_by_currency.map((entry) => {
                        const isPos =
                          typeof entry.balance === "number" && entry.balance >= 0;
                        const balColor =
                          typeof entry.balance === "number"
                            ? isPos
                              ? "#34d399"
                              : "#f87171"
                            : "#94a3b8";

                        return (
                          <div
                            key={entry.currency}
                            style={{
                              background: "rgba(0, 0, 0, 0.25)",
                              border: "1px solid rgba(255, 255, 255, 0.07)",
                              borderRadius: "10px",
                              padding: "12px 14px",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                marginBottom: "6px",
                              }}
                            >
                              <span
                                style={{
                                  fontWeight: 700,
                                  fontSize: "0.82rem",
                                  color: "#a5b4fc",
                                  background: "rgba(99, 102, 241, 0.15)",
                                  border: "1px solid rgba(99, 102, 241, 0.3)",
                                  padding: "2px 8px",
                                  borderRadius: "6px",
                                }}
                              >
                                {entry.currency}
                              </span>
                              <span style={{ fontSize: "0.68rem", color: "#64748b" }}>
                                Net Balance
                              </span>
                            </div>
                            <div
                              style={{
                                fontSize: "1.05rem",
                                fontWeight: 700,
                                color: balColor,
                                marginTop: "4px",
                              }}
                            >
                              {formatMoney(entry.balance, entry.currency)}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Collapsible raw JSON */}
                  {showRawJson && (
                    <div style={{ marginTop: "12px" }}>
                      <div
                        style={{
                          fontWeight: 600,
                          color: "#64748b",
                          fontSize: "0.72rem",
                          marginBottom: "4px",
                        }}
                      >
                        Raw Payload:
                      </div>
                      <pre
                        style={{
                          background: "rgba(0,0,0,0.3)",
                          borderRadius: "8px",
                          padding: "10px",
                          overflow: "auto",
                          maxHeight: "200px",
                          fontSize: "0.72rem",
                          lineHeight: 1.5,
                          color: "#e2e8f0",
                          margin: 0,
                        }}
                      >
                        {JSON.stringify(job.result_payload, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ) : documentPayload ? (
                /* ── DOCUMENT_REPROCESS Result View ── */
                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "10px",
                      flexWrap: "wrap",
                      gap: "8px",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "#cbd5e1" }}>
                      📄 Document Reprocessing Result
                    </div>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <button
                        type="button"
                        id={`toggle-raw-json-btn-${job.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setShowRawJson((prev) => !prev);
                        }}
                        style={{
                          background: showRawJson
                            ? "rgba(255,255,255,0.12)"
                            : "rgba(255,255,255,0.05)",
                          border: "1px solid rgba(255,255,255,0.12)",
                          color: "#94a3b8",
                          borderRadius: "8px",
                          padding: "4px 10px",
                          fontSize: "0.75rem",
                          cursor: "pointer",
                          transition: "all 0.2s",
                        }}
                      >
                        {showRawJson ? "Hide Raw JSON" : "{ } View Raw JSON"}
                      </button>
                    </div>
                  </div>

                  <div
                    style={{
                      background: "rgba(0, 0, 0, 0.25)",
                      border: "1px solid rgba(255, 255, 255, 0.07)",
                      borderRadius: "10px",
                      padding: "12px 14px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "6px",
                      fontSize: "0.8rem",
                    }}
                  >
                    <div>
                      <span style={{ color: "#64748b" }}>Document: </span>
                      <strong style={{ color: "#e2e8f0" }}>
                        {documentPayload.filename || "—"}
                      </strong>
                    </div>
                    <div>
                      <span style={{ color: "#64748b" }}>Status: </span>
                      <span
                        style={{
                          background: "rgba(16, 185, 129, 0.12)",
                          color: "#6ee7b7",
                          border: "1px solid rgba(16, 185, 129, 0.3)",
                          borderRadius: "4px",
                          padding: "2px 6px",
                          fontSize: "0.72rem",
                          fontWeight: 600,
                        }}
                      >
                        {documentPayload.status || "ready_for_reprocess"}
                      </span>
                    </div>
                    {documentPayload.document_id && (
                      <div style={{ fontSize: "0.72rem", color: "#64748b", fontFamily: "monospace" }}>
                        ID: {documentPayload.document_id}
                      </div>
                    )}
                  </div>

                  {/* Collapsible raw JSON */}
                  {showRawJson && (
                    <div style={{ marginTop: "12px" }}>
                      <div
                        style={{
                          fontWeight: 600,
                          color: "#64748b",
                          fontSize: "0.72rem",
                          marginBottom: "4px",
                        }}
                      >
                        Raw Payload:
                      </div>
                      <pre
                        style={{
                          background: "rgba(0,0,0,0.3)",
                          borderRadius: "8px",
                          padding: "10px",
                          overflow: "auto",
                          maxHeight: "200px",
                          fontSize: "0.72rem",
                          lineHeight: 1.5,
                          color: "#e2e8f0",
                          margin: 0,
                        }}
                      >
                        {JSON.stringify(job.result_payload, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ) : (
                /* ── Generic Fallback for unknown / malformed job types ── */
                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "6px",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "#cbd5e1" }}>
                      📋 Result
                    </div>
                    <button
                      type="button"
                      id={`toggle-raw-json-btn-${job.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setShowRawJson((prev) => !prev);
                      }}
                      style={{
                        background: showRawJson
                          ? "rgba(255,255,255,0.12)"
                          : "rgba(255,255,255,0.05)",
                        border: "1px solid rgba(255,255,255,0.12)",
                        color: "#94a3b8",
                        borderRadius: "8px",
                        padding: "4px 10px",
                        fontSize: "0.75rem",
                        cursor: "pointer",
                        transition: "all 0.2s",
                      }}
                    >
                      {showRawJson ? "Hide Raw JSON" : "{ } View Raw JSON"}
                    </button>
                  </div>
                  <pre
                    style={{
                      background: "rgba(0,0,0,0.3)",
                      borderRadius: "8px",
                      padding: "10px",
                      overflow: "auto",
                      maxHeight: "200px",
                      fontSize: "0.72rem",
                      lineHeight: 1.5,
                      color: "#e2e8f0",
                      margin: 0,
                    }}
                  >
                    {JSON.stringify(job.result_payload, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
          {job.parameters && (
            <div style={{ marginTop: "10px" }}>
              <div style={{ fontWeight: 600, color: "#cbd5e1", marginBottom: "6px" }}>
                ⚙ Parameters
              </div>
              <pre
                style={{
                  background: "rgba(0,0,0,0.2)",
                  borderRadius: "8px",
                  padding: "10px",
                  fontSize: "0.72rem",
                  color: "#94a3b8",
                  margin: 0,
                }}
              >
                {JSON.stringify(job.parameters, null, 2)}
              </pre>
            </div>
          )}
          {!job.result_payload && !job.error_message && !job.parameters && (
            <span style={{ color: "#475569" }}>No additional details.</span>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Submit panel                                                         */
/* ------------------------------------------------------------------ */

function SubmitPanel({
  onSubmit,
  submitting,
}: {
  onSubmit: (type: JobType, params?: Record<string, unknown>) => void;
  submitting: boolean;
}) {
  const [selectedType, setSelectedType] = useState<JobType>("ANALYZE_TRANSACTIONS");
  const [docId, setDocId] = useState("");

  const handleSubmit = () => {
    const params =
      selectedType === "DOCUMENT_REPROCESS" && docId.trim()
        ? { document_id: docId.trim() }
        : undefined;
    onSubmit(selectedType, params);
  };

  return (
    <div
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(108,126,224,0.2)",
        borderRadius: "20px",
        padding: "24px",
        marginBottom: "28px",
      }}
    >
      <h3
        style={{
          margin: "0 0 16px",
          fontSize: "1rem",
          fontWeight: 700,
          color: "#c7d2fe",
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}
      >
        ➕ Submit New Job
      </h3>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
          gap: "10px",
          marginBottom: "16px",
        }}
      >
        {JOB_TYPES.map((jt) => (
          <button
            key={jt.type}
            id={`job-type-btn-${jt.type.toLowerCase()}`}
            onClick={() => setSelectedType(jt.type)}
            style={{
              background:
                selectedType === jt.type
                  ? "rgba(108,126,224,0.25)"
                  : "rgba(255,255,255,0.04)",
              border: `1px solid ${selectedType === jt.type ? "rgba(108,126,224,0.6)" : "rgba(255,255,255,0.1)"}`,
              borderRadius: "12px",
              padding: "12px 14px",
              cursor: "pointer",
              textAlign: "left",
              transition: "all 0.2s",
              color: selectedType === jt.type ? "#c7d2fe" : "#94a3b8",
            }}
          >
            <div style={{ fontSize: "1.3rem", marginBottom: "4px" }}>{jt.icon}</div>
            <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: "3px" }}>
              {jt.label}
            </div>
            <div style={{ fontSize: "0.72rem", lineHeight: 1.4 }}>{jt.description}</div>
          </button>
        ))}
      </div>

      {selectedType === "DOCUMENT_REPROCESS" && (
        <div style={{ marginBottom: "14px" }}>
          <label
            htmlFor="doc-id-input"
            style={{ fontSize: "0.8rem", color: "#94a3b8", display: "block", marginBottom: "6px" }}
          >
            Document ID (UUID)
          </label>
          <input
            id="doc-id-input"
            type="text"
            placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
            value={docId}
            onChange={(e) => setDocId(e.target.value)}
            style={{
              width: "100%",
              background: "rgba(0,0,0,0.3)",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: "8px",
              padding: "10px 14px",
              color: "#e2e8f0",
              fontSize: "0.82rem",
              outline: "none",
              boxSizing: "border-box",
            }}
          />
        </div>
      )}

      <button
        id="submit-job-btn"
        onClick={handleSubmit}
        disabled={submitting}
        style={{
          background: submitting
            ? "rgba(108,126,224,0.3)"
            : "linear-gradient(135deg, #6c7ee0, #9c6dda)",
          border: "none",
          borderRadius: "10px",
          padding: "11px 28px",
          color: "#fff",
          fontWeight: 700,
          fontSize: "0.88rem",
          cursor: submitting ? "not-allowed" : "pointer",
          opacity: submitting ? 0.7 : 1,
          transition: "all 0.2s",
        }}
      >
        {submitting ? "Submitting…" : "🚀 Submit Job"}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Stats bar                                                            */
/* ------------------------------------------------------------------ */

function StatsBar({ data }: { data: JobListResponse | null }) {
  if (!data) return null;
  const stats: Array<{ label: string; value: number; color: string }> = [
    { label: "Queued", value: data.queued_count, color: STATUS_COLORS.QUEUED },
    { label: "Running", value: data.running_count, color: STATUS_COLORS.RUNNING },
    { label: "Completed", value: data.completed_count, color: STATUS_COLORS.COMPLETED },
    { label: "Failed", value: data.failed_count, color: STATUS_COLORS.FAILED },
  ];

  return (
    <div
      style={{
        display: "flex",
        gap: "12px",
        marginBottom: "20px",
        flexWrap: "wrap",
      }}
    >
      {stats.map((s) => (
        <div
          key={s.label}
          style={{
            flex: "1 1 110px",
            background: `${s.color}12`,
            border: `1px solid ${s.color}33`,
            borderRadius: "12px",
            padding: "14px 18px",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: "1.6rem", fontWeight: 800, color: s.color }}>
            {s.value}
          </div>
          <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "2px" }}>
            {s.label}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main page component                                                  */
/* ------------------------------------------------------------------ */

export default function JobQueuePage() {
  const [data, setData] = useState<JobListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancellingIds, setCancellingIds] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState<JobStatus | "">("");
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const showToast = (msg: string, type: "success" | "error" = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const fetchJobs = useCallback(async () => {
    try {
      const result = await listJobs(statusFilter as JobStatus | undefined || undefined);
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  // Initial fetch + polling
  useEffect(() => {
    setLoading(true);
    fetchJobs();
    pollRef.current = setInterval(fetchJobs, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchJobs]);

  const handleSubmit = async (type: JobType, params?: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      const res = await submitJob(type, params);
      showToast(`✅ Job submitted! ID: ${res.job_id.slice(0, 8)}…`);
      await fetchJobs();
    } catch (e) {
      showToast(`❌ ${e instanceof Error ? e.message : String(e)}`, "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (jobId: string) => {
    setCancellingIds((prev) => new Set(prev).add(jobId));
    try {
      await cancelJob(jobId);
      showToast(`🚫 Job cancelled.`);
      await fetchJobs();
    } catch (e) {
      showToast(`❌ ${e instanceof Error ? e.message : String(e)}`, "error");
    } finally {
      setCancellingIds((prev) => {
        const next = new Set(prev);
        next.delete(jobId);
        return next;
      });
    }
  };

  const statuses: Array<{ value: JobStatus | ""; label: string }> = [
    { value: "", label: "All" },
    { value: "QUEUED", label: "Queued" },
    { value: "RUNNING", label: "Running" },
    { value: "COMPLETED", label: "Completed" },
    { value: "FAILED", label: "Failed" },
    { value: "CANCELLED", label: "Cancelled" },
  ];

  return (
    <div className="page-content" id="page-job-queue" style={{ maxWidth: "900px" }}>
      {/* Toast */}
      {toast && (
        <div
          id="job-toast"
          style={{
            position: "fixed",
            top: "80px",
            right: "24px",
            background:
              toast.type === "success" ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
            border: `1px solid ${toast.type === "success" ? "rgba(16,185,129,0.4)" : "rgba(239,68,68,0.4)"}`,
            color: toast.type === "success" ? "#6ee7b7" : "#fca5a5",
            borderRadius: "12px",
            padding: "12px 20px",
            fontWeight: 600,
            fontSize: "0.85rem",
            zIndex: 9999,
            backdropFilter: "blur(12px)",
            boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
            maxWidth: "340px",
            animation: "fadeIn 0.2s ease",
          }}
        >
          {toast.msg}
        </div>
      )}

      {/* Page title */}
      <div style={{ marginBottom: "24px" }}>
        <h1 className="page-title" style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "1.6rem" }}>⚡</span>
          Background Job Queue
        </h1>
        <p style={{ color: "#64748b", fontSize: "0.88rem", marginTop: "6px" }}>
          Submit and monitor long-running financial processing tasks. Jobs run in the background
          without blocking the UI. Results are stored and viewable below.
        </p>
      </div>

      {/* Submit panel */}
      <SubmitPanel onSubmit={handleSubmit} submitting={submitting} />

      {/* Stats bar */}
      <StatsBar data={data} />

      {/* Filter bar */}
      <div
        style={{
          display: "flex",
          gap: "8px",
          marginBottom: "20px",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: "0.8rem", color: "#64748b", marginRight: "4px" }}>
          Filter:
        </span>
        {statuses.map((s) => (
          <button
            key={s.value}
            id={`filter-btn-${s.value || "all"}`}
            onClick={() => setStatusFilter(s.value)}
            style={{
              background:
                statusFilter === s.value
                  ? "rgba(108,126,224,0.25)"
                  : "rgba(255,255,255,0.05)",
              border: `1px solid ${statusFilter === s.value ? "rgba(108,126,224,0.5)" : "rgba(255,255,255,0.1)"}`,
              borderRadius: "20px",
              padding: "5px 14px",
              color: statusFilter === s.value ? "#c7d2fe" : "#94a3b8",
              cursor: "pointer",
              fontSize: "0.78rem",
              fontWeight: 600,
              transition: "all 0.2s",
            }}
          >
            {s.label}
          </button>
        ))}
        <div style={{ marginLeft: "auto", fontSize: "0.75rem", color: "#475569" }}>
          {data ? `${data.total_count} job${data.total_count !== 1 ? "s" : ""}` : ""}
          {" · "} auto-refreshes every {POLL_INTERVAL_MS / 1000}s
        </div>
      </div>

      {/* Job list */}
      {loading && !data ? (
        <div style={{ textAlign: "center", padding: "60px", color: "#475569" }}>
          <div className="loading-spinner" aria-label="Loading…" />
          <p style={{ marginTop: "16px" }}>Loading jobs…</p>
        </div>
      ) : error ? (
        <div
          style={{
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.2)",
            borderRadius: "12px",
            padding: "20px",
            color: "#fca5a5",
            fontSize: "0.85rem",
          }}
        >
          ❌ {error}
        </div>
      ) : !data || data.jobs.length === 0 ? (
        <div
          id="no-jobs-placeholder"
          style={{
            textAlign: "center",
            padding: "60px 20px",
            color: "#475569",
            border: "1px dashed rgba(255,255,255,0.1)",
            borderRadius: "20px",
          }}
        >
          <div style={{ fontSize: "3rem", marginBottom: "12px" }}>⚡</div>
          <p style={{ fontSize: "1rem", fontWeight: 600, color: "#64748b" }}>
            No jobs yet
          </p>
          <p style={{ fontSize: "0.82rem", marginTop: "6px" }}>
            Submit a job above to get started.
          </p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {data.jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              onCancel={handleCancel}
              cancelling={cancellingIds.has(job.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
