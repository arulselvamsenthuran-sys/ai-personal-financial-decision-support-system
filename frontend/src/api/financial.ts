/**
 * Financial API client — Phase 14.
 *
 * All calls use `credentials: "include"` for HttpOnly session cookies.
 * The backend is the sole source of truth for all financial data.
 * No API keys, no user_id in requests, no financial calculations.
 */

import { API_BASE_URL } from "../config";

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

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
      res.status,
    );
  }
  return data as T;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/* ------------------------------------------------------------------ */
/* Financial Accounts                                                 */
/* ------------------------------------------------------------------ */

export interface FinancialAccount {
  id: string;
  user_id: string;
  name: string;
  account_type: string;
  institution_name: string | null;
  account_identifier_masked: string | null;
  currency: string;
  opening_balance: string | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export function fetchAccounts(): Promise<FinancialAccount[]> {
  return apiFetch("/api/financial/accounts");
}

/* ------------------------------------------------------------------ */
/* Transactions                                                       */
/* ------------------------------------------------------------------ */

export interface Transaction {
  id: string;
  financial_account_id: string;
  user_id: string;
  transaction_date: string;
  amount: string;
  currency: string;
  transaction_type: string;
  merchant: string | null;
  description: string | null;
  category: string | null;
  status: string;
  source: string;
  created_at: string;
}

export function fetchTransactions(accountId?: string): Promise<Transaction[]> {
  const qs = accountId ? `?account_id=${accountId}` : "";
  return apiFetch(`/api/financial/transactions${qs}`);
}

/* ------------------------------------------------------------------ */
/* Analytics — Summary                                                */
/* ------------------------------------------------------------------ */

export interface AnalyticsSummaryByCurrency {
  currency: string;
  total_income: string;
  total_expenses: string;
  net_cash_flow: string;
  savings_rate: string | null;
  income_transaction_count: number;
  expense_transaction_count: number;
  transaction_count: number;
}

export interface AnalyticsSummaryResponse {
  period_start: string;
  period_end: string;
  by_currency: AnalyticsSummaryByCurrency[];
}

export function fetchAnalyticsSummary(
  period?: string,
): Promise<AnalyticsSummaryResponse> {
  const qs = period ? `?period=${period}` : "";
  return apiFetch(`/api/financial/analytics/summary${qs}`);
}

/* ------------------------------------------------------------------ */
/* Analytics — Monthly                                                */
/* ------------------------------------------------------------------ */

export interface MonthlyDataByCurrency {
  year: number;
  month: number;
  currency: string;
  income: string;
  expenses: string;
  net_cash_flow: string;
  income_transaction_count: number;
  expense_transaction_count: number;
}

export interface MonthlyAnalyticsResponse {
  period_start: string;
  period_end: string;
  monthly_data: MonthlyDataByCurrency[];
}

export function fetchAnalyticsMonthly(
  period?: string,
): Promise<MonthlyAnalyticsResponse> {
  const qs = period ? `?period=${period}` : "";
  return apiFetch(`/api/financial/analytics/monthly${qs}`);
}

/* ------------------------------------------------------------------ */
/* Analytics — Categories                                             */
/* ------------------------------------------------------------------ */

export interface CategoryBreakdownItem {
  currency: string;
  category: string;
  amount: string;
  transaction_count: number;
  percentage: string;
}

export interface CategoryBreakdownResponse {
  period_start: string;
  period_end: string;
  categories: CategoryBreakdownItem[];
}

export function fetchAnalyticsCategories(
  period?: string,
): Promise<CategoryBreakdownResponse> {
  const qs = period ? `?period=${period}` : "";
  return apiFetch(`/api/financial/analytics/categories${qs}`);
}

/* ------------------------------------------------------------------ */
/* Analytics — Recurring                                              */
/* ------------------------------------------------------------------ */

export interface RecurringTransactionItem {
  currency: string;
  merchant: string;
  approximate_amount: string;
  occurrence_count: number;
  detected_frequency: string;
  last_occurrence: string;
  average_days_between: string | null;
}

export interface RecurringTransactionsResponse {
  detected_patterns: RecurringTransactionItem[];
  note: string;
}

export function fetchAnalyticsRecurring(): Promise<RecurringTransactionsResponse> {
  return apiFetch("/api/financial/analytics/recurring");
}

/* ------------------------------------------------------------------ */
/* Insights                                                           */
/* ------------------------------------------------------------------ */

export interface FinancialInsight {
  id: string;
  user_id: string;
  insight_type: string;
  severity: string;
  title: string;
  description: string;
  metric_value: string | null;
  currency: string | null;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
}

export interface InsightsListResponse {
  period_start: string | null;
  period_end: string | null;
  insights: FinancialInsight[];
  total_count: number;
}

export function fetchInsights(
  period?: string,
  generate?: boolean,
): Promise<InsightsListResponse> {
  const params = new URLSearchParams();
  if (period) params.set("period", period);
  if (generate) params.set("generate", "true");
  const qs = params.toString() ? `?${params}` : "";
  return apiFetch(`/api/financial/insights${qs}`);
}

/* ------------------------------------------------------------------ */
/* Decision Support — Analyze (Phase 12)                              */
/* ------------------------------------------------------------------ */

export interface DecisionAnalyzeRequest {
  scenario_type: string;
  amount: number;
  currency: string;
  description?: string;
  period?: string;
}

export interface DataAvailabilityAudit {
  overall_status: string;
  transaction_baseline: string;
  liquidity_data: string;
  simulation_signals: string;
  transaction_count: number;
  months_analyzed: number;
  notes: string[];
}

export interface CashFlowProjection {
  baseline_income: string | null;
  baseline_expenses: string | null;
  baseline_net_cash_flow: string | null;
  baseline_savings_rate: string | null;
  projected_income: string | null;
  projected_expenses: string | null;
  projected_net_cash_flow: string | null;
  projected_savings_rate: string | null;
  net_cash_flow_change: string | null;
  savings_rate_change: string | null;
  is_one_time_impact: boolean;
  impact_summary: string;
}

export interface LiquidityEvaluation {
  status: string;
  known_liquid_balance: string | null;
  projected_balance_after: string | null;
  liquidity_coverage_ratio: string | null;
  is_liquid_balance_sufficient: boolean | null;
  explanation: string;
}

export interface RatioMetric {
  name: string;
  value: string | null;
  unit: string;
  numerator: string;
  denominator: string;
  is_computable: boolean;
  explanation: string;
}

export interface EvidenceItem {
  metric: string;
  value: string;
  unit: string;
  rule: string;
  source: string;
  explanation: string;
}

export interface RiskIndicator {
  code: string;
  severity: string;
  message: string;
  deterministic_rule: string;
  trigger_value: string;
  threshold_value: string;
}

export interface DecisionAnalyzeResponse {
  scenario_type: string;
  currency: string;
  amount: string;
  description: string | null;
  period_start: string;
  period_end: string;
  data_availability: DataAvailabilityAudit;
  cash_flow_projection: CashFlowProjection;
  liquidity_evaluation: LiquidityEvaluation;
  ratios: RatioMetric[];
  evidence: EvidenceItem[];
  risk_indicators: RiskIndicator[];
  warnings: string[];
  disclaimer: string;
}

export function analyzeDecision(
  req: DecisionAnalyzeRequest,
): Promise<DecisionAnalyzeResponse> {
  return apiFetch("/api/financial/decision-support/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

/* ------------------------------------------------------------------ */
/* Decision Support — Explain (Phase 13 / AI)                         */
/* ------------------------------------------------------------------ */

export interface AIExplanationResult {
  summary: string;
  cash_flow_impact_narrative: string;
  liquidity_narrative: string;
  key_tradeoffs: string[];
  data_limitations_noted: string[];
  provider: string;
  model: string;
}

export interface DecisionExplainResponse {
  deterministic_analysis: DecisionAnalyzeResponse;
  ai_explanation: AIExplanationResult | null;
  ai_status: string;
  ai_status_message: string;
  disclaimer: string;
}

export function explainDecision(
  req: DecisionAnalyzeRequest,
): Promise<DecisionExplainResponse> {
  return apiFetch("/api/financial/decision-support/explain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}
