/**
 * Authentication API client for Phase 3.
 * Uses `credentials: "include"` on all calls so that HttpOnly session cookies
 * are transmitted and preserved by the browser.
 */

import { API_BASE_URL } from "../config";

export interface UserResponse {
  id: string;
  email: string;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export interface MessageResponse {
  detail: string;
}

/**
 * Register a new user.
 */
export async function registerUser(email: string, password: string): Promise<UserResponse> {
  const res = await fetch(`${API_BASE_URL}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `Registration failed (${res.status})`);
  }
  return data;
}

/**
 * Log in a user. The backend responds with an HttpOnly Set-Cookie header.
 */
export async function loginUser(email: string, password: string): Promise<UserResponse> {
  const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `Login failed (${res.status})`);
  }
  return data;
}

/**
 * Retrieve the current authenticated user via active session cookie.
 */
export async function getMe(): Promise<UserResponse> {
  const res = await fetch(`${API_BASE_URL}/api/auth/me`, {
    method: "GET",
    credentials: "include",
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Not authenticated (${res.status})`);
  }
  return res.json();
}

/**
 * Log out the current user, revoking the session in DB and clearing the cookie.
 */
export async function logoutUser(): Promise<MessageResponse> {
  const res = await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: "POST",
    credentials: "include",
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `Logout failed (${res.status})`);
  }
  return data;
}

/**
 * Fetch Google OAuth authorization URL.
 */
export async function getOAuthUrl(provider: 'google'): Promise<{ authorization_url: string; state: string }> {
  const res = await fetch(`${API_BASE_URL}/api/auth/oauth/${provider}/url`, {
    method: "GET",
    credentials: "include",
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `Failed to get ${provider} OAuth URL`);
  }
  return data;
}

/**
 * Process Google OAuth callback code and state.
 */
export async function handleOAuthCallback(provider: 'google', code: string, state: string): Promise<UserResponse> {
  const res = await fetch(`${API_BASE_URL}/api/auth/oauth/${provider}/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ code, state }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `${provider} OAuth login failed`);
  }
  return data;
}

