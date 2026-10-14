/**
 * Proactive Intelligence API Client — Phase 18.
 *
 * Scoped to authenticated user session cookies.
 * Deterministic evidence from backend is the sole source of truth.
 */

import { API_BASE_URL } from "../config";
import { ApiError } from "./financial";

export interface InsightEvidence {
  metric: string;
  current_value: number;
  baseline_value: number;
  change_amount: number;
  change_percent: number | null;
  period_label: string;
  details: Record<string, any>;
}

export interface ProactiveInsight {
  id: string;
  insight_type: string;
  severity: "INFO" | "LOW" | "MEDIUM" | "HIGH" | string;
  title: string;
  description: string;
  currency: string;
  evidence: InsightEvidence;
  confidence: "LOW" | "MEDIUM" | "HIGH" | string;
  created_at: string;
}

export interface ProactiveInsightsResponse {
  total_count: number;
  data_sufficient: boolean;
  data_sufficiency_reason: string | null;
  currencies_evaluated: string[];
  insights: ProactiveInsight[];
}

export interface ProactiveExplainResponse {
  insight_id: string;
  insight_type: string;
  explanation: string;
  ai_status: string;
  ai_status_message: string;
  disclaimer: string;
}

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${url}`, {
    credentials: "include",
    ...init,
  });
  if (res.status === 401) {
    throw new ApiError("Session expired — please log in again.", 401);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(
      (data as any).detail || `Request failed (${res.status})`,
      res.status
    );
  }
  return data as T;
}

export function fetchProactiveInsights(): Promise<ProactiveInsightsResponse> {
  return apiFetch("/api/financial/proactive-insights");
}

export function explainProactiveInsight(
  insightId: string,
  question?: string
): Promise<ProactiveExplainResponse> {
  return apiFetch("/api/financial/proactive-insights/explain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ insight_id: insightId, question }),
  });
}
