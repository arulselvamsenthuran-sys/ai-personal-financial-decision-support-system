/**
 * OAuthCallback — handles the browser redirect from Google after OAuth.
 *
 * Google redirects to: http://localhost:5173/auth/callback/google?code=...&state=...
 *
 * This component:
 *  1. Reads `code` and `state` from the URL query string.
 *  2. POSTs them to the backend callback endpoint.
 *  3. The backend validates state, exchanges code, creates a server-side session,
 *     and sets an HttpOnly session cookie in the response.
 *  4. Calls `refreshUser()` so AuthContext learns about the new session.
 *  5. Navigates to the root URL so the main app renders the authenticated view.
 */

import { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { handleOAuthCallback } from "../api/auth";

export default function OAuthCallback() {
  const { refreshUser } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    // Determine provider from current path: /auth/callback/<provider>
    const pathParts = window.location.pathname.split("/");
    const provider = pathParts[pathParts.length - 1] as "google";

    if (!code || !state) {
      setError("Missing OAuth parameters (code or state). Please try signing in again.");
      return;
    }

    let cancelled = false;

    async function finish() {
      try {
        // POST code + state to backend → backend sets HttpOnly session cookie
        await handleOAuthCallback(provider, code!, state!);

        if (cancelled) return;

        // Tell AuthContext to re-fetch /api/auth/me now that the cookie is set
        await refreshUser();

        if (cancelled) return;

        // Navigate to root — App will now render the authenticated dashboard
        window.history.replaceState({}, "", "/");
        // Force a re-render by dispatching a popstate event
        window.dispatchEvent(new PopStateEvent("popstate"));
      } catch (err: unknown) {
        if (cancelled) return;
        const msg =
          err instanceof Error
            ? err.message
            : "Google sign-in failed. Please try again.";
        setError(msg);
      }
    }

    finish();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) {
    return (
      <div className="auth-page">
        <div className="auth-card-wrap" style={{ textAlign: "center", gap: "1.5rem" }}>
          <div className="auth-brand">
            <span className="auth-brand__icon" aria-hidden="true">◈</span>
            <span className="auth-brand__name">AI Financial Support</span>
          </div>
          <h1 className="auth-title" style={{ fontSize: "1.3rem" }}>Sign-in Failed</h1>
          <div className="alert-box alert-box--error" role="alert">{error}</div>
          <button
            type="button"
            className="btn btn--primary btn--full"
            onClick={() => {
              window.history.replaceState({}, "", "/");
              window.dispatchEvent(new PopStateEvent("popstate"));
            }}
          >
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  // Loading state while exchange is in progress
  return (
    <div className="auth-page">
      <div className="auth-card-wrap" style={{ textAlign: "center", gap: "1.5rem", alignItems: "center" }}>
        <div className="auth-brand">
          <span className="auth-brand__icon" aria-hidden="true">◈</span>
          <span className="auth-brand__name">AI Financial Support</span>
        </div>
        <div className="loading-spinner" aria-label="Completing Google sign-in…" />
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
          Completing Google sign-in…
        </p>
      </div>
    </div>
  );
}
