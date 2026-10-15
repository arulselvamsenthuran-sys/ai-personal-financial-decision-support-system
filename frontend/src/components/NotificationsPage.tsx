import { useState, useEffect, useCallback } from "react";
import {
  listNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  deleteNotification,
  type Notification,
} from "../api/monitoring";

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffSecs = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (diffSecs < 60) return "Just now";
  if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)}m ago`;
  if (diffSecs < 86400) return `${Math.floor(diffSecs / 3600)}h ago`;

  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function getNotificationMeta(type: string) {
  switch (type) {
    case "INSIGHT_SUMMARY":
      return {
        icon: "📈",
        label: "Insights Detected",
        color: "#6366f1",
        bg: "rgba(99, 102, 241, 0.15)",
        actionLink: "/analytics",
        actionText: "📊 View Insights",
      };
    case "MONITORING_NO_CHANGE":
      return {
        icon: "🛡️",
        label: "Financial Review Stable",
        color: "#10b981",
        bg: "rgba(16, 185, 129, 0.15)",
        actionLink: "/dashboard",
        actionText: "📊 Dashboard",
      };
    case "MONITORING_STARTED":
      return {
        icon: "⏳",
        label: "Monitoring Started",
        color: "#38bdf8",
        bg: "rgba(56, 189, 248, 0.15)",
        actionLink: "/jobs",
        actionText: "⚡ Job Queue",
      };
    case "JOB_FAILED":
      return {
        icon: "⚠️",
        label: "Monitoring Error",
        color: "#ef4444",
        bg: "rgba(239, 68, 68, 0.15)",
        actionLink: "/jobs",
        actionText: "⚡ Check Jobs",
      };
    default:
      return {
        icon: "💡",
        label: "Notification",
        color: "#94a3b8",
        bg: "rgba(148, 163, 184, 0.15)",
        actionLink: null,
        actionText: null,
      };
  }
}

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"ALL" | "UNREAD">("ALL");
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const showToast = (msg: string, type: "success" | "error" = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const fetchNotifications = useCallback(async () => {
    try {
      setError(null);
      const isReadParam = filter === "UNREAD" ? false : undefined;
      const res = await listNotifications(isReadParam);
      setNotifications(res.notifications);
      setUnreadCount(res.unread_count);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  const handleMarkRead = async (notif: Notification) => {
    if (notif.is_read) return;
    setActionLoadingId(notif.id);
    try {
      await markNotificationRead(notif.id);
      await fetchNotifications();
    } catch (err) {
      showToast(`❌ ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleMarkAllRead = async () => {
    if (unreadCount === 0) return;
    try {
      const res = await markAllNotificationsRead();
      showToast(`✅ Marked ${res.marked_count} notifications as read.`);
      await fetchNotifications();
    } catch (err) {
      showToast(`❌ ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  };

  const handleDelete = async (notif: Notification) => {
    setActionLoadingId(notif.id);
    try {
      await deleteNotification(notif.id);
      showToast("🗑️ Notification removed.");
      await fetchNotifications();
    } catch (err) {
      showToast(`❌ ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setActionLoadingId(null);
    }
  };

  return (
    <div className="page-content" id="page-notifications">
      {/* Toast */}
      {toast && (
        <div className={`toast toast--${toast.type}`} role="alert">
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div
        className="page-header"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: "1.5rem",
          flexWrap: "wrap",
          gap: "1rem",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <h1 className="page-title" style={{ margin: 0 }}>Notifications</h1>
            {unreadCount > 0 && (
              <span
                style={{
                  background: "#ef4444",
                  color: "white",
                  fontSize: "0.8rem",
                  fontWeight: 700,
                  padding: "0.15rem 0.6rem",
                  borderRadius: "999px",
                }}
              >
                {unreadCount} new
              </span>
            )}
          </div>
          <p className="page-subtitle" style={{ color: "var(--color-text-secondary, #94a3b8)", marginTop: "0.25rem" }}>
            Alerts, monitoring results, and automated financial insights.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {unreadCount > 0 && (
            <button
              className="btn btn--secondary btn--small"
              onClick={handleMarkAllRead}
              id="btn-mark-all-read"
            >
              ✓ Mark All as Read
            </button>
          )}
        </div>
      </div>

      {/* Filter Tabs */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        <button
          className={`btn btn--small ${filter === "ALL" ? "btn--primary" : "btn--secondary"}`}
          onClick={() => setFilter("ALL")}
        >
          All
        </button>
        <button
          className={`btn btn--small ${filter === "UNREAD" ? "btn--primary" : "btn--secondary"}`}
          onClick={() => setFilter("UNREAD")}
        >
          Unread ({unreadCount})
        </button>
      </div>

      {/* Error State */}
      {error && (
        <div className="alert alert--error" style={{ marginBottom: "1.5rem" }}>
          {error}
          <button className="btn btn--small" onClick={fetchNotifications} style={{ marginLeft: "1rem" }}>
            Retry
          </button>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "3rem" }}>
          <div className="loading-spinner" aria-label="Loading notifications…" />
        </div>
      ) : notifications.length === 0 ? (
        <div
          style={{
            textAlign: "center",
            padding: "4rem 2rem",
            background: "rgba(30, 41, 59, 0.4)",
            borderRadius: "16px",
            border: "1px dashed rgba(255, 255, 255, 0.15)",
          }}
        >
          <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>🔔</div>
          <h2 style={{ fontSize: "1.25rem", margin: "0 0 0.5rem 0" }}>No Notifications</h2>
          <p style={{ color: "#94a3b8", maxWidth: "420px", margin: "0 auto" }}>
            {filter === "UNREAD"
              ? "You have caught up with all notifications!"
              : "Notifications from scheduled audits and insight checks will appear here."}
          </p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          {notifications.map((notif) => {
            const isProcessing = actionLoadingId === notif.id;
            const meta = getNotificationMeta(notif.notification_type);
            return (
              <div
                key={notif.id}
                className="notification-item"
                onClick={() => handleMarkRead(notif)}
                style={{
                  background: notif.is_read ? "rgba(30, 41, 59, 0.4)" : "rgba(30, 41, 59, 0.8)",
                  border: `1px solid ${notif.is_read ? "rgba(255, 255, 255, 0.06)" : "rgba(99, 102, 241, 0.4)"}`,
                  borderLeft: `4px solid ${meta.color}`,
                  borderRadius: "12px",
                  padding: "1.1rem 1.25rem",
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: "1rem",
                  cursor: notif.is_read ? "default" : "pointer",
                  transition: "background 0.15s, border-color 0.15s",
                }}
              >
                <div style={{ display: "flex", gap: "0.85rem", flex: 1 }}>
                  <div style={{ fontSize: "1.5rem", lineHeight: 1 }}>{meta.icon}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.35rem", flexWrap: "wrap" }}>
                      <span
                        style={{
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          padding: "0.15rem 0.5rem",
                          borderRadius: "4px",
                          background: meta.bg,
                          color: meta.color,
                        }}
                      >
                        {meta.label}
                      </span>
                      <h3
                        style={{
                          margin: 0,
                          fontSize: "1rem",
                          fontWeight: notif.is_read ? 500 : 700,
                          color: notif.is_read ? "#e2e8f0" : "white",
                        }}
                      >
                        {notif.title}
                      </h3>
                      {!notif.is_read && (
                        <span
                          style={{
                            width: "8px",
                            height: "8px",
                            borderRadius: "50%",
                            background: meta.color,
                            display: "inline-block",
                          }}
                        />
                      )}
                    </div>
                    <div
                      style={{
                        margin: "0 0 0.5rem 0",
                        color: "#cbd5e1",
                        fontSize: "0.9rem",
                        lineHeight: 1.5,
                        whiteSpace: "pre-line",
                      }}
                    >
                      {notif.body}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginTop: "0.35rem", flexWrap: "wrap" }}>
                      <span style={{ fontSize: "0.78rem", color: "#94a3b8" }}>
                        {formatTimestamp(notif.created_at)}
                      </span>
                      {meta.actionLink && (
                        <button
                          type="button"
                          className="btn btn--small btn--secondary"
                          style={{ fontSize: "0.78rem", padding: "0.2rem 0.6rem" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(meta.actionLink!);
                          }}
                        >
                          {meta.actionText}
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                  {!notif.is_read && (
                    <button
                      className="btn btn--small btn--secondary"
                      disabled={isProcessing}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleMarkRead(notif);
                      }}
                      title="Mark as read"
                    >
                      ✓ Read
                    </button>
                  )}
                  <button
                    className="btn btn--small btn--danger"
                    disabled={isProcessing}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(notif);
                    }}
                    title="Delete notification"
                  >
                    ✕
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
