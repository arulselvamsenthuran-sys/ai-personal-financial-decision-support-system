import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { getOAuthUrl } from "../api/auth";

type View = "login" | "register";

// Google "G" SVG icon (official colors)
function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 0 0 2.38-5.88c0-.57-.05-.66-.15-1.18z"
        fill="#4285F4"
      />
      <path
        d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2a4.8 4.8 0 0 1-7.18-2.54H1.83v2.07A8 8 0 0 0 8.98 17z"
        fill="#34A853"
      />
      <path
        d="M4.5 10.52a4.8 4.8 0 0 1 0-3.04V5.41H1.83a8 8 0 0 0 0 7.18z"
        fill="#FBBC05"
      />
      <path
        d="M8.98 4.18c1.17 0 2.23.4 3.06 1.2l2.3-2.3A8 8 0 0 0 1.83 5.4L4.5 7.49a4.77 4.77 0 0 1 4.48-3.3z"
        fill="#EA4335"
      />
    </svg>
  );
}

export default function AuthPage() {
  const { login, register } = useAuth();
  const [view, setView] = useState<View>("login");

  // Login state
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  // Register state
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regConfirm, setRegConfirm] = useState("");
  const [regLoading, setRegLoading] = useState(false);
  const [regError, setRegError] = useState<string | null>(null);
  const [regSuccess, setRegSuccess] = useState<string | null>(null);

  // OAuth state
  const [oauthLoading, setOauthLoading] = useState(false);
  const [oauthError, setOauthError] = useState<string | null>(null);

  const switchToLogin = () => {
    setView("login");
    setRegError(null);
    setRegSuccess(null);
    setOauthError(null);
  };

  const switchToRegister = () => {
    setView("register");
    setLoginError(null);
    setOauthError(null);
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError(null);
    setLoginLoading(true);
    try {
      await login(loginEmail, loginPassword);
    } catch (err: unknown) {
      setLoginError(err instanceof Error ? err.message : "Invalid email or password.");
    } finally {
      setLoginLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setRegError(null);
    setRegSuccess(null);

    if (regPassword !== regConfirm) {
      setRegError("Passwords do not match.");
      return;
    }
    if (regPassword.length < 8) {
      setRegError("Password must be at least 8 characters.");
      return;
    }

    setRegLoading(true);
    try {
      await register(regEmail, regPassword);
      setRegSuccess("Account created! You can now log in.");
      setLoginEmail(regEmail);
      setRegEmail("");
      setRegPassword("");
      setRegConfirm("");
      setTimeout(() => switchToLogin(), 1500);
    } catch (err: unknown) {
      setRegError(err instanceof Error ? err.message : "Registration failed. Please try again.");
    } finally {
      setRegLoading(false);
    }
  };

  const handleGoogleOAuth = async () => {
    setOauthError(null);
    setOauthLoading(true);
    try {
      const { authorization_url } = await getOAuthUrl("google");
      window.location.href = authorization_url;
    } catch (err: unknown) {
      setOauthError(err instanceof Error ? err.message : "Failed to start Google sign-in.");
      setOauthLoading(false);
    }
  };

  if (view === "login") {
    return (
      <div className="auth-page">
        <div className="auth-card-wrap">
          {/* Brand */}
          <div className="auth-brand">
            <span className="auth-brand__icon" aria-hidden="true">◈</span>
            <span className="auth-brand__name">AI Financial Support</span>
          </div>

          <h1 className="auth-title">Welcome Back</h1>

          {/* Login form */}
          <form className="auth-form" onSubmit={handleLogin} noValidate>
            <div className="form-group">
              <label htmlFor="login-email" className="form-label">Email Address</label>
              <input
                id="login-email"
                type="email"
                className="form-input"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoComplete="email"
                disabled={loginLoading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="login-password" className="form-label">Password</label>
              <input
                id="login-password"
                type="password"
                className="form-input"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                placeholder="••••••••"
                required
                autoComplete="current-password"
                disabled={loginLoading}
              />
            </div>

            {loginError && (
              <div className="alert-box alert-box--error" role="alert">{loginError}</div>
            )}

            <button
              type="submit"
              className="btn btn--primary btn--full"
              disabled={loginLoading}
            >
              {loginLoading ? <span className="btn-spinner" aria-hidden="true" /> : null}
              {loginLoading ? "Signing in…" : "Login"}
            </button>
          </form>

          <div className="auth-divider" aria-hidden="true">
            <span>OR</span>
          </div>

          {/* Google OAuth */}
          <button
            type="button"
            className="btn btn--google btn--full"
            onClick={handleGoogleOAuth}
            disabled={oauthLoading}
            id="btn-google-login"
          >
            {oauthLoading ? (
              <span className="btn-spinner btn-spinner--dark" aria-hidden="true" />
            ) : (
              <GoogleIcon />
            )}
            {oauthLoading ? "Redirecting…" : "Continue with Google"}
          </button>

          {oauthError && (
            <div className="alert-box alert-box--error" role="alert">{oauthError}</div>
          )}

          {/* Switch to register */}
          <p className="auth-switch">
            Don't have an account?{" "}
            <button
              type="button"
              className="auth-switch__link"
              onClick={switchToRegister}
              id="btn-go-register"
            >
              Create Account
            </button>
          </p>
        </div>
      </div>
    );
  }

  // Register view
  return (
    <div className="auth-page">
      <div className="auth-card-wrap">
        {/* Brand */}
        <div className="auth-brand">
          <span className="auth-brand__icon" aria-hidden="true">◈</span>
          <span className="auth-brand__name">AI Financial Support</span>
        </div>

        <h1 className="auth-title">Create Account</h1>

        <form className="auth-form" onSubmit={handleRegister} noValidate>
          <div className="form-group">
            <label htmlFor="reg-email" className="form-label">Email Address</label>
            <input
              id="reg-email"
              type="email"
              className="form-input"
              value={regEmail}
              onChange={(e) => setRegEmail(e.target.value)}
              placeholder="you@example.com"
              required
              autoComplete="email"
              disabled={regLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="reg-password" className="form-label">Password</label>
            <input
              id="reg-password"
              type="password"
              className="form-input"
              value={regPassword}
              onChange={(e) => setRegPassword(e.target.value)}
              placeholder="Min. 8 characters"
              required
              autoComplete="new-password"
              disabled={regLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="reg-confirm" className="form-label">Confirm Password</label>
            <input
              id="reg-confirm"
              type="password"
              className="form-input"
              value={regConfirm}
              onChange={(e) => setRegConfirm(e.target.value)}
              placeholder="••••••••"
              required
              autoComplete="new-password"
              disabled={regLoading}
            />
          </div>

          {regError && (
            <div className="alert-box alert-box--error" role="alert">{regError}</div>
          )}
          {regSuccess && (
            <div className="alert-box alert-box--success" role="status">{regSuccess}</div>
          )}

          <button
            type="submit"
            className="btn btn--primary btn--full"
            disabled={regLoading}
          >
            {regLoading ? <span className="btn-spinner" aria-hidden="true" /> : null}
            {regLoading ? "Creating account…" : "Create Account"}
          </button>
        </form>

        <div className="auth-divider" aria-hidden="true">
          <span>OR</span>
        </div>

        {/* Google OAuth on register screen */}
        <button
          type="button"
          className="btn btn--google btn--full"
          onClick={handleGoogleOAuth}
          disabled={oauthLoading}
          id="btn-google-signup"
        >
          {oauthLoading ? (
            <span className="btn-spinner btn-spinner--dark" aria-hidden="true" />
          ) : (
            <GoogleIcon />
          )}
          {oauthLoading ? "Redirecting…" : "Sign up with Google"}
        </button>

        {oauthError && (
          <div className="alert-box alert-box--error" role="alert">{oauthError}</div>
        )}

        <p className="auth-switch">
          Already have an account?{" "}
          <button
            type="button"
            className="auth-switch__link"
            onClick={switchToLogin}
            id="btn-go-login"
          >
            Login
          </button>
        </p>
      </div>
    </div>
  );
}
