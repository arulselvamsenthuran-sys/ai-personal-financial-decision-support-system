import { useEffect, useState, useCallback } from "react";
import { useTheme } from "../context/ThemeContext";
import { useAuth } from "../context/AuthContext";
import {
  listSchedules,
  toggleSchedule,
  getUnreadCount,
  markAllNotificationsRead,
  type MonitoringSchedule,
} from "../api/monitoring";
import HealthStatus from "./HealthStatus";
import {
  PaletteIcon,
  GlobeIcon,
  BellIcon,
  ShieldCheckIcon,
  ActivityIcon,
} from "./Icons";

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const { user, logout } = useAuth();

  /* Local Preferences */
  const [dateFormat, setDateFormat] = useState<string>(() => {
    return localStorage.getItem("financesupport_date_format") || "YYYY-MM-DD";
  });
  const [inAppAlerts, setInAppAlerts] = useState<boolean>(() => {
    const saved = localStorage.getItem("financesupport_inapp_alerts");
    return saved !== null ? saved === "true" : true;
  });

  /* Feedback Toast */
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  /* Automated Monitoring Schedules */
  const [schedules, setSchedules] = useState<MonitoringSchedule[]>([]);
  const [loadingSchedules, setLoadingSchedules] = useState(false);
  const [togglingScheduleId, setTogglingScheduleId] = useState<string | null>(null);

  /* Notifications Count */
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [markingRead, setMarkingRead] = useState(false);

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((cur) => (cur === msg ? null : cur));
    }, 3500);
  }, []);

  const loadMonitoringData = useCallback(async () => {
    setLoadingSchedules(true);
    try {
      const [schedRes, unreadRes] = await Promise.all([
        listSchedules().catch(() => ({ schedules: [], total_count: 0 })),
        getUnreadCount().catch(() => ({ unread_count: 0 })),
      ]);
      setSchedules(schedRes.schedules);
      setUnreadCount(unreadRes.unread_count);
    } finally {
      setLoadingSchedules(false);
    }
  }, []);

  useEffect(() => {
    loadMonitoringData();
  }, [loadMonitoringData]);

  /* Handlers */
  const handleThemeChange = (newTheme: "dark" | "light") => {
    if (newTheme !== theme) {
      setTheme(newTheme);
      showToast(`Appearance updated to ${newTheme === "dark" ? "Dark Mode" : "Light Mode"}.`);
    }
  };

  const handleDateFormatChange = (fmt: string) => {
    setDateFormat(fmt);
    try {
      localStorage.setItem("financesupport_date_format", fmt);
    } catch {
      /* quota */
    }
    showToast(`Date format preference saved: ${fmt}`);
  };

  const handleInAppAlertsToggle = () => {
    const next = !inAppAlerts;
    setInAppAlerts(next);
    try {
      localStorage.setItem("financesupport_inapp_alerts", String(next));
    } catch {
      /* quota */
    }
    showToast(next ? "In-app alert banners enabled." : "In-app alert banners disabled.");
  };

  const handleToggleSchedule = async (s: MonitoringSchedule) => {
    setTogglingScheduleId(s.id);
    try {
      const updated = await toggleSchedule(s.id);
      setSchedules((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      showToast(
        `Schedule "${s.name}" is now ${updated.is_enabled ? "active" : "paused"}.`
      );
    } catch (err: any) {
      showToast(`Failed to update schedule: ${err.message}`);
    } finally {
      setTogglingScheduleId(null);
    }
  };

  const handleMarkAllRead = async () => {
    if (unreadCount === 0) return;
    setMarkingRead(true);
    try {
      await markAllNotificationsRead();
      setUnreadCount(0);
      showToast("All notifications marked as read.");
    } catch (err: any) {
      showToast(`Could not mark notifications: ${err.message}`);
    } finally {
      setMarkingRead(false);
    }
  };

  /* Helper to format today's date for live preview */
  const formatPreviewDate = (fmt: string): string => {
    const now = new Date();
    const yyyy = now.getFullYear();
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const dd = String(now.getDate()).padStart(2, "0");
    if (fmt === "DD/MM/YYYY") return `${dd}/${mm}/${yyyy}`;
    if (fmt === "MM/DD/YYYY") return `${mm}/${dd}/${yyyy}`;
    return `${yyyy}-${mm}-${dd}`;
  };

  return (
    <div className="page-content" id="page-settings">
      {/* Toast Feedback */}
      {toastMessage && (
        <div className="settings-toast-alert" role="status" aria-live="polite">
          <span className="toast-icon">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </span>
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Page Header */}
      <div className="page-header-row" style={{ marginBottom: "2rem" }}>
        <div>
          <h1 className="page-title" style={{ marginBottom: "0.25rem" }}>
            Settings & Preferences
          </h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.92rem", margin: 0 }}>
            Manage appearance, regional preferences, monitoring schedules, and account security.
          </p>
        </div>
      </div>

      <div className="settings-sections-wrapper" style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
        {/* ── Section 1: Appearance ── */}
        <section className="card settings-section-card" id="settings-appearance">
          <div className="settings-section-header">
            <div className="settings-icon-bubble">
              <PaletteIcon size={20} style={{ color: "var(--color-primary)" }} />
            </div>
            <div>
              <h2 className="card__title" style={{ margin: 0 }}>Appearance & Theme</h2>
              <p className="settings-section-desc">
                Select your preferred color scheme. The theme persists across all application views.
              </p>
            </div>
          </div>

          <div className="theme-selection-grid" style={{ marginTop: "1.25rem" }}>
            {/* Dark Theme Tile */}
            <div
              className={`theme-tile-card ${theme === "dark" ? "theme-tile--active" : ""}`}
              onClick={() => handleThemeChange("dark")}
              role="button"
              tabIndex={0}
              id="theme-select-dark"
              onKeyDown={(e) => e.key === "Enter" && handleThemeChange("dark")}
            >
              <div className="theme-tile-preview theme-tile-preview--dark">
                <div className="preview-mini-header" />
                <div className="preview-mini-content">
                  <div className="preview-mini-sidebar" />
                  <div className="preview-mini-cards">
                    <div className="preview-mini-card" />
                    <div className="preview-mini-card" />
                  </div>
                </div>
              </div>
              <div className="theme-tile-info">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span className="theme-tile-name">Dark Mode</span>
                  {theme === "dark" && <span className="theme-badge-active">Active</span>}
                </div>
                <span className="theme-tile-desc">High contrast navy & slate palette for low-light environments.</span>
              </div>
            </div>

            {/* Light Theme Tile */}
            <div
              className={`theme-tile-card ${theme === "light" ? "theme-tile--active" : ""}`}
              onClick={() => handleThemeChange("light")}
              role="button"
              tabIndex={0}
              id="theme-select-light"
              onKeyDown={(e) => e.key === "Enter" && handleThemeChange("light")}
            >
              <div className="theme-tile-preview theme-tile-preview--light">
                <div className="preview-mini-header" />
                <div className="preview-mini-content">
                  <div className="preview-mini-sidebar" />
                  <div className="preview-mini-cards">
                    <div className="preview-mini-card" />
                    <div className="preview-mini-card" />
                  </div>
                </div>
              </div>
              <div className="theme-tile-info">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span className="theme-tile-name">Light Mode</span>
                  {theme === "light" && <span className="theme-badge-active">Active</span>}
                </div>
                <span className="theme-tile-desc">Crisp white and neutral slate theme with refined legibility.</span>
              </div>
            </div>
          </div>
        </section>

        {/* ── Section 2: Regional & Display Formatting ── */}
        <section className="card settings-section-card" id="settings-regional">
          <div className="settings-section-header">
            <div className="settings-icon-bubble">
              <GlobeIcon size={20} style={{ color: "var(--color-info)" }} />
            </div>
            <div>
              <h2 className="card__title" style={{ margin: 0 }}>Regional & Display Preferences</h2>
              <p className="settings-section-desc">
                Configure date representation and review currency calculation boundaries.
              </p>
            </div>
          </div>

          <div className="settings-control-list" style={{ marginTop: "1.25rem", display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            {/* Date Format */}
            <div className="settings-row-item">
              <div className="settings-row-text">
                <label className="settings-label" htmlFor="select-date-format">Date Display Format</label>
                <span className="settings-hint">
                  Controls how dates appear across transactions, activity feeds, and scheduled audits.
                </span>
                <span className="settings-preview-tag" style={{ marginTop: "0.35rem", display: "inline-block" }}>
                  Preview: <strong>{formatPreviewDate(dateFormat)}</strong>
                </span>
              </div>
              <div className="settings-row-control">
                <select
                  id="select-date-format"
                  className="form-input"
                  style={{ minWidth: "180px" }}
                  value={dateFormat}
                  onChange={(e) => handleDateFormatChange(e.target.value)}
                >
                  <option value="YYYY-MM-DD">YYYY-MM-DD (ISO)</option>
                  <option value="DD/MM/YYYY">DD/MM/YYYY (Day-First)</option>
                  <option value="MM/DD/YYYY">MM/DD/YYYY (Month-First)</option>
                </select>
              </div>
            </div>

            {/* Currency Handling Note */}
            <div className="settings-row-item" style={{ borderTop: "1px solid var(--color-border-subtle)", paddingTop: "1.25rem" }}>
              <div className="settings-row-text">
                <span className="settings-label">Currency Boundaries & Precision</span>
                <span className="settings-hint">
                  Each financial account maintains its native ISO-4217 code (e.g. LKR, USD, EUR) to preserve exact ledger balance calculations without floating-point conversion loss.
                </span>
              </div>
              <div className="settings-row-control">
                <span className="status-pill status-pill--active" style={{ fontSize: "0.8rem" }}>
                  Multi-Currency Ledger Active
                </span>
              </div>
            </div>

            {/* Language Note */}
            <div className="settings-row-item" style={{ borderTop: "1px solid var(--color-border-subtle)", paddingTop: "1.25rem" }}>
              <div className="settings-row-text">
                <span className="settings-label">System Language</span>
                <span className="settings-hint">
                  English (US/UK) is the standard active system locale.
                </span>
              </div>
              <div className="settings-row-control">
                <span className="status-pill" style={{ background: "var(--color-surface-alt)", color: "var(--color-text-muted)" }}>
                  English (en-US)
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* ── Section 3: Notifications & Monitoring Schedules ── */}
        <section className="card settings-section-card" id="settings-notifications">
          <div className="settings-section-header">
            <div className="settings-icon-bubble">
              <BellIcon size={20} style={{ color: "var(--color-warning)" }} />
            </div>
            <div>
              <h2 className="card__title" style={{ margin: 0 }}>Automated Monitoring & Alerts</h2>
              <p className="settings-section-desc">
                Manage backend routine monitoring schedules and notification preferences.
              </p>
            </div>
          </div>

          <div style={{ marginTop: "1.25rem", display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            {/* In-App Alerts Banner Toggle */}
            <div className="settings-row-item">
              <div className="settings-row-text">
                <span className="settings-label">In-App Alert Toasts</span>
                <span className="settings-hint">
                  Display subtle alert banners when new AI insights or background tasks complete.
                </span>
              </div>
              <div className="settings-row-control">
                <button
                  type="button"
                  className={`btn ${inAppAlerts ? "btn--primary" : "btn--secondary"}`}
                  onClick={handleInAppAlertsToggle}
                  style={{ minWidth: "100px" }}
                  id="btn-toggle-inapp-alerts"
                >
                  {inAppAlerts ? "Enabled" : "Disabled"}
                </button>
              </div>
            </div>

            {/* Notification Inbox Quick Action */}
            <div className="settings-row-item" style={{ borderTop: "1px solid var(--color-border-subtle)", paddingTop: "1.25rem" }}>
              <div className="settings-row-text">
                <span className="settings-label">Unread Notifications</span>
                <span className="settings-hint">
                  {unreadCount > 0
                    ? `You currently have ${unreadCount} unread system notification(s).`
                    : "No unread notifications at this time."}
                </span>
              </div>
              <div className="settings-row-control" style={{ display: "flex", gap: "0.5rem" }}>
                {unreadCount > 0 && (
                  <button
                    type="button"
                    className="btn btn--secondary"
                    onClick={handleMarkAllRead}
                    disabled={markingRead}
                    id="btn-settings-mark-all-read"
                  >
                    {markingRead ? "Marking…" : "Mark All Read"}
                  </button>
                )}
                <a href="#/notifications" className="btn btn--secondary" style={{ textDecoration: "none" }}>
                  Open Inbox
                </a>
              </div>
            </div>

            {/* Automated Schedules List */}
            <div style={{ borderTop: "1px solid var(--color-border-subtle)", paddingTop: "1.25rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                <span className="settings-label">Routine Monitoring Schedules</span>
                <a href="#/schedules" style={{ fontSize: "0.82rem", color: "var(--color-primary)", textDecoration: "none", fontWeight: 600 }}>
                  + New Schedule
                </a>
              </div>

              {loadingSchedules ? (
                <div style={{ padding: "1rem 0", color: "var(--color-text-dim)", fontSize: "0.85rem" }}>
                  Loading schedules…
                </div>
              ) : schedules.length === 0 ? (
                <p className="empty-text" style={{ padding: "0.5rem 0", margin: 0, fontSize: "0.88rem" }}>
                  No automated schedules configured. Set up daily or weekly routine checks in the Schedules tab.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                  {schedules.map((s) => (
                    <div
                      key={s.id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        padding: "0.75rem 1rem",
                        background: "var(--color-surface-alt)",
                        borderRadius: "var(--radius-md)",
                        border: "1px solid var(--color-border-subtle)",
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, fontSize: "0.9rem", color: "var(--color-text)" }}>
                          {s.name}
                        </div>
                        <div style={{ fontSize: "0.78rem", color: "var(--color-text-dim)" }}>
                          {s.frequency} at {String(s.hour_of_day).padStart(2, "0")}:00 UTC
                        </div>
                      </div>
                      <button
                        type="button"
                        className={`btn btn--small ${s.is_enabled ? "btn--primary" : "btn--secondary"}`}
                        style={{ minWidth: "85px" }}
                        disabled={togglingScheduleId === s.id}
                        onClick={() => handleToggleSchedule(s)}
                      >
                        {togglingScheduleId === s.id ? "…" : s.is_enabled ? "Active" : "Paused"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>

        {/* ── Section 4: Privacy & Account Identity ── */}
        <section className="card settings-section-card" id="settings-privacy">
          <div className="settings-section-header">
            <div className="settings-icon-bubble">
              <ShieldCheckIcon size={20} style={{ color: "var(--color-success)" }} />
            </div>
            <div>
              <h2 className="card__title" style={{ margin: 0 }}>Account Security & Privacy</h2>
              <p className="settings-section-desc">
                Authenticated session properties and tenant isolation protections.
              </p>
            </div>
          </div>

          <div style={{ marginTop: "1.25rem", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "1rem" }}>
            <div className="security-info-box">
              <span className="security-info-label">Account Email</span>
              <span className="security-info-val">{user?.email ?? "—"}</span>
            </div>

            <div className="security-info-box">
              <span className="security-info-label">Account Status</span>
              <span className="security-info-val">
                <span className="status-pill status-pill--active">
                  {user?.is_active ? "Active" : "Suspended"}
                </span>
              </span>
            </div>

            <div className="security-info-box">
              <span className="security-info-label">Member Since</span>
              <span className="security-info-val">
                {user?.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}
              </span>
            </div>

            <div className="security-info-box">
              <span className="security-info-label">Tenant Identifier</span>
              <span className="security-info-val mono" style={{ fontSize: "0.78rem", color: "var(--color-text-dim)" }}>
                {user?.id ? `${user.id.slice(0, 8)}••••••••${user.id.slice(-4)}` : "—"}
              </span>
            </div>
          </div>

          <div style={{ marginTop: "1.5rem", padding: "1rem", background: "var(--color-surface-alt)", borderRadius: "var(--radius-md)", border: "1px solid var(--color-border-subtle)" }}>
            <div style={{ fontWeight: 600, fontSize: "0.88rem", marginBottom: "0.4rem", color: "var(--color-text)" }}>
              Active Security Protections
            </div>
            <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.82rem", color: "var(--color-text-muted)", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
              <li>HttpOnly server-side session cookie with SameSite protection against XSS and CSRF.</li>
              <li>Argon2id cryptographic password hashing with unique salt.</li>
              <li>Strict row-level user tenant separation on all financial queries.</li>
            </ul>
          </div>

          <div style={{ marginTop: "1.5rem", display: "flex", justifyContent: "flex-end" }}>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={logout}
              style={{ color: "var(--color-danger)", borderColor: "rgba(239, 68, 68, 0.3)" }}
              id="btn-settings-logout"
            >
              Sign Out of Session
            </button>
          </div>
        </section>

        {/* ── Section 5: System Health Diagnostics ── */}
        <section className="card settings-section-card" id="settings-system-health">
          <div className="settings-section-header">
            <div className="settings-icon-bubble">
              <ActivityIcon size={20} style={{ color: "var(--color-accent)" }} />
            </div>
            <div>
              <h2 className="card__title" style={{ margin: 0 }}>System Health & Configuration</h2>
              <p className="settings-section-desc">
                Live backend connectivity and operational service diagnostics.
              </p>
            </div>
          </div>

          <div style={{ marginTop: "1.25rem" }}>
            <HealthStatus />
          </div>

          <div style={{ marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid var(--color-border-subtle)", display: "flex", justifyContent: "space-between", fontSize: "0.78rem", color: "var(--color-text-dim)" }}>
            <span>Client Version: FinanceSupport Web v1.0.0</span>
            <span>API Standard: OpenAPI 3.1</span>
          </div>
        </section>
      </div>
    </div>
  );
}
