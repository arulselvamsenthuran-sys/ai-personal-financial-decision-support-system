import { useState, useEffect, useCallback } from "react";
import {
  listSchedules,
  createSchedule,
  toggleSchedule,
  deleteSchedule,
  triggerSchedule,
  type MonitoringSchedule,
  type FrequencyType,
} from "../api/monitoring";

const DAYS_OF_WEEK = [
  { value: 1, label: "Monday" },
  { value: 2, label: "Tuesday" },
  { value: 3, label: "Wednesday" },
  { value: 4, label: "Thursday" },
  { value: 5, label: "Friday" },
  { value: 6, label: "Saturday" },
  { value: 7, label: "Sunday" },
];

function formatTime(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getFrequencyLabel(sched: MonitoringSchedule): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const timeStr = `${pad(sched.hour_of_day)}:00 UTC`;

  if (sched.frequency === "DAILY") {
    return `Daily at ${timeStr}`;
  }
  const dayName =
    DAYS_OF_WEEK.find((d) => d.value === sched.day_of_week)?.label ?? `Day ${sched.day_of_week}`;
  return `Weekly on ${dayName} at ${timeStr}`;
}

export default function SchedulingPage() {
  const [schedules, setSchedules] = useState<MonitoringSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  // Form State
  const [name, setName] = useState("");
  const [frequency, setFrequency] = useState<FrequencyType>("DAILY");
  const [dayOfWeek, setDayOfWeek] = useState<number>(1);
  const [hourOfDay, setHourOfDay] = useState<number>(8);
  const [submitting, setSubmitting] = useState(false);

  const showToast = (msg: string, type: "success" | "error" = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const fetchSchedules = useCallback(async () => {
    try {
      setError(null);
      const res = await listSchedules();
      setSchedules(res.schedules);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSchedules();
  }, [fetchSchedules]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setSubmitting(true);
    try {
      await createSchedule({
        name: name.trim(),
        frequency,
        day_of_week: frequency === "WEEKLY" ? dayOfWeek : undefined,
        hour_of_day: hourOfDay,
        is_enabled: true,
      });
      showToast("✅ Monitoring schedule created!");
      setShowModal(false);
      setName("");
      setFrequency("DAILY");
      setHourOfDay(8);
      await fetchSchedules();
    } catch (err) {
      showToast(`❌ ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggle = async (schedule: MonitoringSchedule) => {
    setActionLoadingId(schedule.id);
    try {
      await toggleSchedule(schedule.id);
      showToast(
        schedule.is_enabled ? "⏸️ Schedule paused" : "▶️ Schedule enabled"
      );
      await fetchSchedules();
    } catch (err) {
      showToast(`❌ ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleTrigger = async (schedule: MonitoringSchedule) => {
    setActionLoadingId(schedule.id);
    try {
      await triggerSchedule(schedule.id);
      showToast(`⚡ Analysis triggered for "${schedule.name}"!`);
      await fetchSchedules();
    } catch (err) {
      showToast(`❌ ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleDelete = async (schedule: MonitoringSchedule) => {
    if (!window.confirm(`Delete monitoring schedule "${schedule.name}"?`)) return;

    setActionLoadingId(schedule.id);
    try {
      await deleteSchedule(schedule.id);
      showToast("🗑️ Schedule deleted.");
      await fetchSchedules();
    } catch (err) {
      showToast(`❌ ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setActionLoadingId(null);
    }
  };

  const activeCount = schedules.filter((s) => s.is_enabled).length;

  return (
    <div className="page-content" id="page-scheduling">
      {/* Toast */}
      {toast && (
        <div className={`toast toast--${toast.type}`} role="alert">
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>Scheduled Financial Monitoring</h1>
          <p className="page-subtitle" style={{ color: "var(--color-text-secondary, #94a3b8)", marginTop: "0.25rem" }}>
            Automate routine health audits and portfolio intelligence checks.
          </p>
        </div>
        <button
          className="btn btn--primary"
          id="btn-create-schedule"
          onClick={() => setShowModal(true)}
          style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}
        >
          <span>＋</span> New Schedule
        </button>
      </div>

      {/* Stats Cards */}
      <div className="stats-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
        <div className="stat-card" style={{ background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(255, 255, 255, 0.1)", borderRadius: "12px", padding: "1.25rem" }}>
          <div style={{ color: "#94a3b8", fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Total Schedules</div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, marginTop: "0.5rem" }}>{schedules.length}</div>
        </div>
        <div className="stat-card" style={{ background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(255, 255, 255, 0.1)", borderRadius: "12px", padding: "1.25rem" }}>
          <div style={{ color: "#10b981", fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Active Monitors</div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, marginTop: "0.5rem", color: "#10b981" }}>{activeCount}</div>
        </div>
        <div className="stat-card" style={{ background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(255, 255, 255, 0.1)", borderRadius: "12px", padding: "1.25rem" }}>
          <div style={{ color: "#94a3b8", fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Paused</div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, marginTop: "0.5rem" }}>{schedules.length - activeCount}</div>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="alert alert--error" style={{ marginBottom: "1.5rem" }}>
          {error}
          <button className="btn btn--small" onClick={fetchSchedules} style={{ marginLeft: "1rem" }}>
            Retry
          </button>
        </div>
      )}

      {/* Loading state */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "3rem" }}>
          <div className="loading-spinner" aria-label="Loading schedules…" />
        </div>
      ) : schedules.length === 0 ? (
        <div style={{ textAlign: "center", padding: "4rem 2rem", background: "rgba(30, 41, 59, 0.4)", borderRadius: "16px", border: "1px dashed rgba(255, 255, 255, 0.15)" }}>
          <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>⏰</div>
          <h2 style={{ fontSize: "1.25rem", margin: "0 0 0.5rem 0" }}>No Monitoring Schedules Configured</h2>
          <p style={{ color: "#94a3b8", maxWidth: "450px", margin: "0 auto 1.5rem auto" }}>
            Set up automated periodic monitoring to proactively audit your transactions, generate financial insights, and receive in-app notifications.
          </p>
          <button className="btn btn--primary" onClick={() => setShowModal(true)}>
            Create First Schedule
          </button>
        </div>
      ) : (
        /* Schedule List */
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {schedules.map((sched) => {
            const isProcessing = actionLoadingId === sched.id;
            return (
              <div
                key={sched.id}
                className="schedule-card"
                style={{
                  background: "rgba(30, 41, 59, 0.6)",
                  border: `1px solid ${sched.is_enabled ? "rgba(99, 102, 241, 0.3)" : "rgba(255, 255, 255, 0.08)"}`,
                  borderRadius: "14px",
                  padding: "1.25rem 1.5rem",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  flexWrap: "wrap",
                  gap: "1rem",
                  transition: "transform 0.15s, border-color 0.15s",
                }}
              >
                <div style={{ flex: 1, minWidth: "260px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.35rem" }}>
                    <span style={{ fontSize: "1.25rem" }}>{sched.frequency === "DAILY" ? "📅" : "🗓️"}</span>
                    <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 600 }}>{sched.name}</h3>
                    <span
                      style={{
                        padding: "0.2rem 0.6rem",
                        borderRadius: "999px",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        background: sched.is_enabled ? "rgba(16, 185, 129, 0.15)" : "rgba(107, 114, 128, 0.2)",
                        color: sched.is_enabled ? "#10b981" : "#94a3b8",
                        border: `1px solid ${sched.is_enabled ? "rgba(16, 185, 129, 0.3)" : "rgba(107, 114, 128, 0.3)"}`,
                      }}
                    >
                      {sched.is_enabled ? "Active" : "Paused"}
                    </span>
                  </div>
                  <div style={{ color: "#94a3b8", fontSize: "0.875rem", display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
                    <span>🔄 {getFrequencyLabel(sched)}</span>
                    <span>⏳ Next: {sched.is_enabled ? formatTime(sched.next_run_at) : "Paused"}</span>
                    <span>✔️ Last: {formatTime(sched.last_run_at)}</span>
                  </div>
                </div>

                {/* Actions */}
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <button
                    className="btn btn--small btn--primary"
                    disabled={isProcessing}
                    onClick={() => handleTrigger(sched)}
                    title="Run schedule immediately in background"
                    style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}
                  >
                    <span>⚡</span> Run Now
                  </button>
                  <button
                    className={`btn btn--small ${sched.is_enabled ? "btn--secondary" : "btn--success"}`}
                    disabled={isProcessing}
                    onClick={() => handleToggle(sched)}
                    style={{ minWidth: "75px" }}
                  >
                    {sched.is_enabled ? "Pause" : "Resume"}
                  </button>
                  <button
                    className="btn btn--small btn--danger"
                    disabled={isProcessing}
                    onClick={() => handleDelete(sched)}
                    title="Delete schedule"
                  >
                    🗑️
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Create Modal */}
      {showModal && (
        <div
          className="modal-overlay"
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(6px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "1rem",
          }}
          onClick={() => setShowModal(false)}
        >
          <div
            className="modal-card"
            style={{
              background: "#1e293b",
              borderRadius: "16px",
              padding: "2rem",
              width: "100%",
              maxWidth: "500px",
              border: "1px solid rgba(255, 255, 255, 0.15)",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2 style={{ margin: "0 0 1rem 0", fontSize: "1.35rem" }}>Create Monitoring Schedule</h2>
            <form onSubmit={handleCreate}>
              <div style={{ marginBottom: "1.25rem" }}>
                <label style={{ display: "block", fontSize: "0.875rem", color: "#cbd5e1", marginBottom: "0.4rem" }}>
                  Schedule Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Daily Portfolio Morning Check"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "0.75rem",
                    borderRadius: "8px",
                    background: "#0f172a",
                    border: "1px solid rgba(255, 255, 255, 0.15)",
                    color: "white",
                    fontSize: "0.95rem",
                  }}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.25rem" }}>
                <div>
                  <label style={{ display: "block", fontSize: "0.875rem", color: "#cbd5e1", marginBottom: "0.4rem" }}>
                    Frequency
                  </label>
                  <select
                    value={frequency}
                    onChange={(e) => setFrequency(e.target.value as FrequencyType)}
                    style={{
                      width: "100%",
                      padding: "0.75rem",
                      borderRadius: "8px",
                      background: "#0f172a",
                      border: "1px solid rgba(255, 255, 255, 0.15)",
                      color: "white",
                      fontSize: "0.95rem",
                    }}
                  >
                    <option value="DAILY">Daily</option>
                    <option value="WEEKLY">Weekly</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "0.875rem", color: "#cbd5e1", marginBottom: "0.4rem" }}>
                    Execution Hour (UTC)
                  </label>
                  <select
                    value={hourOfDay}
                    onChange={(e) => setHourOfDay(Number(e.target.value))}
                    style={{
                      width: "100%",
                      padding: "0.75rem",
                      borderRadius: "8px",
                      background: "#0f172a",
                      border: "1px solid rgba(255, 255, 255, 0.15)",
                      color: "white",
                      fontSize: "0.95rem",
                    }}
                  >
                    {Array.from({ length: 24 }).map((_, h) => (
                      <option key={h} value={h}>
                        {String(h).padStart(2, "0")}:00 UTC
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {frequency === "WEEKLY" && (
                <div style={{ marginBottom: "1.25rem" }}>
                  <label style={{ display: "block", fontSize: "0.875rem", color: "#cbd5e1", marginBottom: "0.4rem" }}>
                    Day of the Week
                  </label>
                  <select
                    value={dayOfWeek}
                    onChange={(e) => setDayOfWeek(Number(e.target.value))}
                    style={{
                      width: "100%",
                      padding: "0.75rem",
                      borderRadius: "8px",
                      background: "#0f172a",
                      border: "1px solid rgba(255, 255, 255, 0.15)",
                      color: "white",
                      fontSize: "0.95rem",
                    }}
                  >
                    {DAYS_OF_WEEK.map((d) => (
                      <option key={d.value} value={d.value}>
                        {d.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "1.5rem" }}>
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={() => setShowModal(false)}
                  disabled={submitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={submitting || !name.trim()}
                >
                  {submitting ? "Creating…" : "Save Schedule"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
