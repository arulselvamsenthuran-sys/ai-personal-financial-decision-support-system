import { useState, useEffect } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import AuthPage from "./components/AuthPage";
import OAuthCallback from "./components/OAuthCallback";
import HealthStatus from "./components/HealthStatus";
import DashboardPage from "./components/DashboardPage";
import AccountsPage from "./components/AccountsPage";
import TransactionsPage from "./components/TransactionsPage";
import AnalyticsPage from "./components/AnalyticsPage";
import DecisionSupportPage from "./components/DecisionSupportPage";
import ConversationsPage from "./components/ConversationsPage";
import JobQueuePage from "./components/JobQueuePage";  // Phase 19
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
/* Navigation items                                                   */
/* ------------------------------------------------------------------ */

const NAV_ITEMS = [
  { path: "/dashboard",        label: "Dashboard",         icon: "📊" },
  { path: "/accounts",         label: "Accounts",          icon: "🏦" },
  { path: "/transactions",     label: "Transactions",      icon: "💳" },
  { path: "/analytics",        label: "Analytics",         icon: "📈" },
  { path: "/decision-support", label: "Decision Support",  icon: "🎯" },
  { path: "/conversations",     label: "AI Conversations",  icon: "💬" },
  { path: "/jobs",             label: "Job Queue",          icon: "⚡" },  // Phase 19
];

/* ------------------------------------------------------------------ */
/* Header                                                             */
/* ------------------------------------------------------------------ */

function HeaderNav() {
  const { user, isAuthenticated, logout } = useAuth();

  return (
    <header className="app-header">
      <div
        className="logo"
        id="app-logo"
        onClick={() => navigate("/dashboard")}
        style={{ cursor: "pointer" }}
      >
        <span className="logo__icon">◈</span>
        <span className="logo__text">Finance Support</span>
      </div>
      <div className="header-actions">
        {isAuthenticated && user && (
          <span className="user-badge" id="user-badge-email">
            {user.email}
          </span>
        )}
        {isAuthenticated && (
          <button className="btn btn--small btn--danger" onClick={logout}>
            Logout
          </button>
        )}
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Sidebar                                                            */
/* ------------------------------------------------------------------ */

function Sidebar() {
  const pathname = usePathname();
  const activePath = pathname === "/" ? "/dashboard" : pathname;

  return (
    <nav className="sidebar" id="app-sidebar">
      {NAV_ITEMS.map((item) => (
        <button
          key={item.path}
          className={`sidebar__item${activePath === item.path ? " sidebar__item--active" : ""}`}
          onClick={() => navigate(item.path)}
          id={`nav-${item.path.replace("/", "")}`}
        >
          <span className="sidebar__icon">{item.icon}</span>
          <span className="sidebar__label">{item.label}</span>
        </button>
      ))}
      <div className="sidebar__spacer" />
      <button
        className={`sidebar__item${activePath === "/system" ? " sidebar__item--active" : ""}`}
        onClick={() => navigate("/system")}
        id="nav-system"
      >
        <span className="sidebar__icon">⚙️</span>
        <span className="sidebar__label">System</span>
      </button>
    </nav>
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
    case "/decision-support":
      return <DecisionSupportPage />;
    case "/conversations":
      return <ConversationsPage />;
    case "/jobs":
      return <JobQueuePage />;  // Phase 19
    case "/system":
      return (
        <div className="page-content" id="page-system">
          <h1 className="page-title">System Health</h1>
          <HealthStatus />
        </div>
      );
    default:
      return (
        <div className="page-content">
          <h1 className="page-title">Page Not Found</h1>
          <p className="empty-text">The page "{pathname}" does not exist.</p>
          <button className="btn btn--primary" onClick={() => navigate("/dashboard")} style={{ marginTop: "1rem" }}>
            Go to Dashboard
          </button>
        </div>
      );
  }
}

/* ------------------------------------------------------------------ */
/* Main Layout                                                        */
/* ------------------------------------------------------------------ */

function AppContent() {
  const { isAuthenticated, loading } = useAuth();
  const pathname = usePathname();

  // Handle OAuth provider callbacks BEFORE checking auth state.
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
        <div className="loading-spinner" aria-label="Loading…" />
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
    <div className="app-layout">
      <Sidebar />
      <main className="app-main app-main--page">
        <ProtectedRoute>
          <PageRouter />
        </ProtectedRoute>
      </main>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* App root                                                           */
/* ------------------------------------------------------------------ */

function App() {
  return (
    <AuthProvider>
      <div className="app">
        {/* Animated background particles */}
        <div className="bg-particles" aria-hidden="true">
          <div className="particle particle--1" />
          <div className="particle particle--2" />
          <div className="particle particle--3" />
        </div>

        <HeaderNav />
        <AppContent />

        <footer className="app-footer">
          <p>AI Financial Support &middot; Secure &middot; Private</p>
        </footer>
      </div>
    </AuthProvider>
  );
}

export default App;
