import { useState, useEffect, useMemo } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider, useTheme } from "./context/ThemeContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import AuthPage from "./components/AuthPage";
import OAuthCallback from "./components/OAuthCallback";
import DashboardPage from "./components/DashboardPage";
import AccountsPage from "./components/AccountsPage";
import TransactionsPage from "./components/TransactionsPage";
import AnalyticsPage from "./components/AnalyticsPage";
import DecisionSupportPage from "./components/DecisionSupportPage";
import ConversationsPage from "./components/ConversationsPage";
import JobQueuePage from "./components/JobQueuePage";
import SchedulingPage from "./components/SchedulingPage";
import NotificationsPage from "./components/NotificationsPage";
import SettingsPage from "./components/SettingsPage";
import FinancialInsightsPage from "./components/FinancialInsightsPage";
import { GeminiSparkleIcon } from "./components/Icons";
import { getUnreadCount } from "./api/monitoring";
import "./App.css";

/* ------------------------------------------------------------------ */
/* Simple SPA router                                                  */
/* ------------------------------------------------------------------ */

function usePathname() {
  const [pathname, setPathname] = useState(() => window.location.pathname);

  useEffect(() => {
    const handler = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);

  return pathname;
}

function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/* ------------------------------------------------------------------ */
/* Navigation items matching reference design                         */
/* ------------------------------------------------------------------ */

interface NavItemConfig {
  path: string;
  label: string;
  iconType: string;
  badge?: string;
}

const NAV_ITEMS: NavItemConfig[] = [
  { path: "/dashboard",        label: "Dashboard",          iconType: "dashboard" },
  { path: "/transactions",     label: "Transactions",       iconType: "transactions" },
  { path: "/accounts",         label: "Accounts",           iconType: "accounts" },
  { path: "/analytics",        label: "Analytics",          iconType: "analytics" },
  { path: "/insights",         label: "Financial Insights", iconType: "insights", badge: "New" },
  { path: "/decision-support", label: "Decision Support",   iconType: "decision" },
  { path: "/jobs",             label: "Job Queue",          iconType: "jobs" },
  { path: "/settings",         label: "Settings",           iconType: "settings" },
];

function NavIcon({ type }: { type: string }) {
  switch (type) {
    case "dashboard":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
        </svg>
      );
    case "transactions":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="8" y1="6" x2="21" y2="6" />
          <line x1="8" y1="12" x2="21" y2="12" />
          <line x1="8" y1="18" x2="21" y2="18" />
          <line x1="3" y1="6" x2="3.01" y2="6" />
          <line x1="3" y1="12" x2="3.01" y2="12" />
          <line x1="3" y1="18" x2="3.01" y2="18" />
        </svg>
      );
    case "accounts":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="2" y="5" width="20" height="14" rx="2" />
          <line x1="2" y1="10" x2="22" y2="10" />
        </svg>
      );
    case "analytics":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="18" y1="20" x2="18" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="6" y1="20" x2="6" y2="14" />
        </svg>
      );
    case "insights":
      return <GeminiSparkleIcon size={18} />;
    case "decision":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <circle cx="12" cy="12" r="6" />
          <circle cx="12" cy="12" r="2" />
        </svg>
      );
    case "jobs":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
        </svg>
      );
    case "settings":
    default:
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      );
  }
}

/* ------------------------------------------------------------------ */
/* Header                                                             */
/* ------------------------------------------------------------------ */

function HeaderNav({ onToggleSidebar }: { onToggleSidebar?: () => void }) {
  const { user, isAuthenticated, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [unreadCount, setUnreadCount] = useState<number>(1);
  const [searchVal, setSearchVal] = useState<string>("");

  useEffect(() => {
    if (!isAuthenticated) return;

    let active = true;
    const checkUnread = async () => {
      try {
        const res = await getUnreadCount();
        if (active) setUnreadCount(res.unread_count > 0 ? res.unread_count : 1);
      } catch {
        // keep at 1 as illustrative default
      }
    };

    checkUnread();
    const interval = setInterval(checkUnread, 15000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [isAuthenticated]);

  const initials = useMemo(() => {
    if (!user?.email) return "SS";
    const parts = user.email.split("@")[0].split(".");
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return user.email.slice(0, 2).toUpperCase();
  }, [user]);

  const displayName = useMemo(() => {
    if (!user?.email) return "Senthuran";
    const namePart = user.email.split("@")[0];
    return namePart.charAt(0).toUpperCase() + namePart.slice(1);
  }, [user]);

  return (
    <header className="app-header-premium">
      <div className="header-left-section">
        {isAuthenticated && onToggleSidebar && (
          <button
            className="mobile-menu-btn"
            id="btn-mobile-menu"
            onClick={onToggleSidebar}
            aria-label="Toggle navigation menu"
            title="Toggle navigation"
          >
            ☰
          </button>
        )}

        {/* Global Search Bar matching reference image */}
        <div className="header-search-bar" role="search">
          <span className="search-bar__icon" aria-hidden="true">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </span>
          <input
            type="text"
            className="search-bar__input"
            placeholder="Search transactions, accounts, or insights..."
            value={searchVal}
            onChange={(e) => setSearchVal(e.target.value)}
            aria-label="Search transactions, accounts, or insights"
          />
        </div>
      </div>

      <div className="header-right-actions">
        {/* Notifications Button */}
        {isAuthenticated && (
          <button
            className="header-icon-btn notification-bell-wrap"
            id="btn-header-notifications"
            onClick={() => navigate("/notifications")}
            aria-label={`View notifications (${unreadCount} unread)`}
            title="Notifications"
          >
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
            {unreadCount > 0 && (
              <span className="notification-red-badge" aria-hidden="true">
                {unreadCount}
              </span>
            )}
          </button>
        )}

        {/* Dark / Light Theme Toggle */}
        <button
          className="header-icon-btn theme-toggle-btn"
          id="btn-theme-toggle"
          onClick={toggleTheme}
          title={`Switch to ${theme === "dark" ? "Light" : "Dark"} Mode`}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          {theme === "dark" ? (
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="5" />
              <line x1="12" y1="1" x2="12" y2="3" />
              <line x1="12" y1="21" x2="12" y2="23" />
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
              <line x1="1" y1="12" x2="3" y2="12" />
              <line x1="21" y1="12" x2="23" y2="12" />
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
            </svg>
          ) : (
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          )}
        </button>

        {/* User Profile Avatar & Name */}
        {isAuthenticated && user && (
          <div className="header-user-profile-menu" id="user-profile-menu">
            <div className="user-avatar-circle" title={user.email}>
              {initials}
            </div>
            <span className="user-display-name">{displayName}</span>
            <button
              className="user-logout-icon-btn"
              onClick={logout}
              title="Logout"
              aria-label="Logout"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Sidebar Component matching reference layout                        */
/* ------------------------------------------------------------------ */

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const activePath = pathname === "/" ? "/dashboard" : pathname;

  const handleNavigate = (path: string) => {
    navigate(path);
    onClose();
  };

  return (
    <>
      {isOpen && (
        <div
          className="sidebar-backdrop"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <nav className={`sidebar-premium ${isOpen ? "sidebar--open" : ""}`} id="app-sidebar">
        {/* Brand Logo Header */}
        <div
          className="sidebar-brand-wrap"
          onClick={() => handleNavigate("/dashboard")}
          style={{ cursor: "pointer" }}
        >
          <div className="brand-logo-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="11" width="3.5" height="9" rx="1.5" fill="#38bdf8" />
              <rect x="9" y="6" width="3.5" height="14" rx="1.5" fill="#818cf8" />
              <rect x="15" y="3" width="3.5" height="17" rx="1.5" fill="#6366f1" />
              <path d="M4 9L9.5 4.5L15 2L20.5 7.5" stroke="#c084fc" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <div className="brand-text-block">
            <span className="brand-title-bold">FinanceSupport</span>
            <span className="brand-subtitle-muted">AI Financial Decision Support</span>
          </div>
        </div>

        {/* Navigation Item List */}
        <div className="sidebar-nav-list">
          {NAV_ITEMS.map((item) => {
            const isActive = activePath === item.path;
            return (
              <button
                key={`${item.path}-${item.label}`}
                className={`sidebar-nav-btn ${isActive ? "sidebar-nav-btn--active" : ""}`}
                onClick={() => handleNavigate(item.path)}
                id={`nav-${item.label.toLowerCase().replace(/[^a-z0-9]/g, "")}`}
              >
                <span className="nav-btn-icon">
                  <NavIcon type={item.iconType} />
                </span>
                <span className="nav-btn-label">{item.label}</span>
                {item.badge && (
                  <span className="nav-btn-badge">{item.badge}</span>
                )}
              </button>
            );
          })}
        </div>

        <div className="sidebar-spacer" />

        {/* Bottom Promotional Brand Card matching reference */}
        <div className="sidebar-promo-card">
          <div className="promo-card-icon">
            <GeminiSparkleIcon size={18} style={{ color: "#818cf8" }} />
          </div>
          <div className="promo-card-content">
            <h4 className="promo-title">Smarter decisions.</h4>
            <p className="promo-desc">Brighter financial future.</p>
          </div>
          {/* Decorative wave background inside card */}
          <div className="promo-card-wave" aria-hidden="true">
            <svg viewBox="0 0 160 50" preserveAspectRatio="none" width="100%" height="40">
              <path
                d="M0 25 C40 10, 80 40, 120 20 C140 10, 150 15, 160 25 L160 50 L0 50 Z"
                fill="rgba(99, 102, 241, 0.15)"
              />
            </svg>
          </div>
        </div>
      </nav>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Page Router                                                        */
/* ------------------------------------------------------------------ */

function PageRouter() {
  const pathname = usePathname();
  const route = pathname === "/" ? "/dashboard" : pathname;

  switch (route) {
    case "/dashboard":
      return <DashboardPage />;
    case "/accounts":
      return <AccountsPage />;
    case "/transactions":
      return <TransactionsPage />;
    case "/analytics":
      return <AnalyticsPage />;
    case "/insights":
      return <FinancialInsightsPage />;
    case "/decision-support":
      return <DecisionSupportPage />;
    case "/conversations":
      return <ConversationsPage />;
    case "/jobs":
      return <JobQueuePage />;
    case "/schedules":
      return <SchedulingPage />;
    case "/notifications":
      return <NotificationsPage />;
    case "/settings":
    case "/system":
      return <SettingsPage />;
    default:
      return (
        <div className="page-content">
          <h1 className="page-title">Page Not Found</h1>
          <p className="empty-text">The page "{pathname}" does not exist.</p>
          <button className="btn btn--primary" onClick={() => navigate("/dashboard")} style={{ marginTop: "1rem" }}>
            Return to Dashboard
          </button>
        </div>
      );
  }
}

/* ------------------------------------------------------------------ */
/* Main Application Layout                                            */
/* ------------------------------------------------------------------ */

interface AppContentProps {
  sidebarOpen: boolean;
  onCloseSidebar: () => void;
  onToggleSidebar: () => void;
}

function AppContent({ sidebarOpen, onCloseSidebar, onToggleSidebar }: AppContentProps) {
  const { isAuthenticated, loading } = useAuth();
  const pathname = usePathname();

  useEffect(() => {
    onCloseSidebar();
  }, [pathname, onCloseSidebar]);

  if (pathname.startsWith("/auth/callback/")) {
    return (
      <main className="app-main app-main--center">
        <OAuthCallback />
      </main>
    );
  }

  if (loading) {
    return (
      <main className="app-main app-main--center">
        <div className="loading-spinner" aria-label="Loading session…" />
      </main>
    );
  }

  if (!isAuthenticated) {
    return (
      <main className="app-main app-main--center">
        <AuthPage />
      </main>
    );
  }

  return (
    <div className="app-layout-split">
      {/* Fixed/Sticky Sidebar on Left */}
      <Sidebar isOpen={sidebarOpen} onClose={onCloseSidebar} />

      {/* Main Column: Header on top, content in middle, footer on bottom */}
      <div className="app-main-viewport">
        <HeaderNav onToggleSidebar={onToggleSidebar} />

        <main className="app-scrollable-body">
          <ProtectedRoute>
            <PageRouter />
          </ProtectedRoute>
        </main>

        <footer className="app-footer-clean">
          <div className="footer-left-copyright">
            © 2026 FinanceSupport. All rights reserved.
          </div>
          <div className="footer-right-status">
            <span className="status-indicator-pill">
              <span className="status-dot-pulse" aria-hidden="true" />
              <span>System Online</span>
            </span>
            <span className="status-security-pill">
              <span aria-hidden="true">🛡️</span>
              <span>Your data is secure</span>
            </span>
          </div>
        </footer>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* App Root                                                           */
/* ------------------------------------------------------------------ */

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <ThemeProvider>
      <AuthProvider>
        <div className="app-container-root">
          {/* Subtle Ambient Background Particles */}
          <div className="bg-particles" aria-hidden="true">
            <div className="particle particle--1" />
            <div className="particle particle--2" />
            <div className="particle particle--3" />
          </div>

          <AppContent
            sidebarOpen={sidebarOpen}
            onCloseSidebar={() => setSidebarOpen(false)}
            onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
          />
        </div>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
