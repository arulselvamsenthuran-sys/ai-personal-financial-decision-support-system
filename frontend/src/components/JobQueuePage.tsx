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

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + "…" : s;
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
  const typeInfo = JOB_TYPES.find((t) => t.type === job.job_type);
  const canCancel = job.status === "QUEUED" || job.status === "RUNNING";

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
              <div style={{ fontWeight: 600, color: "#cbd5e1", marginBottom: "6px" }}>
                📋 Result
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
      setError(String(e));
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
      showToast(`❌ ${e}`, "error");
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
      showToast(`❌ ${e}`, "error");
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
