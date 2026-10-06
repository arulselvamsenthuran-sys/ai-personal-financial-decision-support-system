import { useEffect, useState } from "react";
import {
  fetchAccounts,
  fetchAnalyticsSummary,
  fetchTransactions,
  fetchInsights,
  type FinancialAccount,
  type AnalyticsSummaryByCurrency,
  type Transaction,
  type FinancialInsight,
} from "../api/financial";

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

const INSIGHT_ICONS: Record<string, string> = {
  HIGH_EXPENSE_CATEGORY: "⚠️",
  EXPENSE_INCREASE: "📈",
  NEGATIVE_CASH_FLOW: "🔻",
  RECURRING_EXPENSE_DETECTED: "🔄",
  INCOME_DECREASE: "📉",
  LARGE_TRANSACTION: "💰",
};

const SEVERITY_CLASS: Record<string, string> = {
  critical: "severity--critical",
  warning: "severity--warning",
  info: "severity--info",
};

function fmt(v: string | null | undefined, currency?: string): string {
  if (v === null || v === undefined) return "Unavailable";
  const n = Number(v);
  if (isNaN(n)) return v;
  return currency
    ? `${currency} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ------------------------------------------------------------------ */
/* Component                                                          */
/* ------------------------------------------------------------------ */

export default function DashboardPage() {
  const [accounts, setAccounts] = useState<FinancialAccount[]>([]);
  const [summary, setSummary] = useState<AnalyticsSummaryByCurrency[]>([]);
  const [recentTxns, setRecentTxns] = useState<Transaction[]>([]);
  const [insights, setInsights] = useState<FinancialInsight[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [accts, sum, txns, ins] = await Promise.all([
          fetchAccounts(),
          fetchAnalyticsSummary("last_3_months").then((r) => r.by_currency),
          fetchTransactions().then((r) => r.slice(0, 8)),
          fetchInsights("last_3_months", true).then((r) => r.insights),
        ]);
        setAccounts(accts);
        setSummary(sum);
        setRecentTxns(txns);
        setInsights(ins);
      } catch (e: any) {
        setError(e.message ?? "Failed to load dashboard data");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <div className="page-loading"><div className="loading-spinner" /><p>Loading dashboard…</p></div>;
  if (error) return <div className="alert-box alert-box--error">{error}</div>;

  return (
    <div className="page-content" id="page-dashboard">
      <h1 className="page-title">Dashboard</h1>

      {/* ── Financial Overview ── */}
      <section className="card" id="dashboard-overview">
        <h2 className="card__title">Financial Overview</h2>
        {summary.length === 0 ? (
          <p className="empty-text">No financial data available. Upload a bank statement to get started.</p>
        ) : (
          <div className="metric-grid">
            {summary.map((s) => (
              <div key={s.currency} className="metric-group">
                <span className="metric-group__currency">{s.currency}</span>
                <div className="metric-row">
                  <MetricCard label="Total Income" value={fmt(s.total_income, s.currency)} accent="success" />
                  <MetricCard label="Total Expenses" value={fmt(s.total_expenses, s.currency)} accent="danger" />
                  <MetricCard label="Net Cash Flow" value={fmt(s.net_cash_flow, s.currency)} accent={Number(s.net_cash_flow) >= 0 ? "success" : "danger"} />
                  <MetricCard label="Savings Rate" value={s.savings_rate !== null ? `${Number(s.savings_rate).toFixed(1)}%` : "Unavailable"} accent="primary" />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Accounts ── */}
      <section className="card" id="dashboard-accounts">
        <h2 className="card__title">Financial Accounts</h2>
        {accounts.length === 0 ? (
          <p className="empty-text">No accounts found.</p>
        ) : (
          <div className="compact-table-wrap">
            <table className="data-table data-table--compact">
              <thead>
                <tr><th>Name</th><th>Type</th><th>Institution</th><th>Currency</th><th>Status</th></tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id}>
                    <td>{a.name}</td>
                    <td className="tag">{a.account_type}</td>
                    <td>{a.institution_name ?? "—"}</td>
                    <td>{a.currency}</td>
                    <td><span className={`dot ${a.is_active ? "dot--active" : "dot--inactive"}`} />{a.is_active ? "Active" : "Inactive"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Recent Transactions ── */}
      <section className="card" id="dashboard-recent-txns">
        <h2 className="card__title">Recent Transactions</h2>
        {recentTxns.length === 0 ? (
          <p className="empty-text">No transactions found.</p>
        ) : (
          <div className="compact-table-wrap">
            <table className="data-table data-table--compact">
              <thead>
                <tr><th>Date</th><th>Description</th><th>Amount</th><th>Type</th></tr>
              </thead>
              <tbody>
                {recentTxns.map((t) => (
                  <tr key={t.id}>
                    <td className="mono">{t.transaction_date}</td>
                    <td>{t.description || t.merchant || "—"}</td>
                    <td className={`mono ${t.transaction_type === "credit" ? "text-success" : "text-danger"}`}>{fmt(t.amount, t.currency)}</td>
                    <td className="tag">{t.transaction_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Insights ── */}
      <section className="card" id="dashboard-insights">
        <h2 className="card__title">Financial Insights</h2>
        {insights.length === 0 ? (
          <p className="empty-text">No insights generated yet.</p>
        ) : (
          <div className="insight-list">
            {insights.map((ins) => (
              <div key={ins.id} className={`insight-item ${SEVERITY_CLASS[ins.severity] ?? ""}`}>
                <span className="insight-item__icon">{INSIGHT_ICONS[ins.insight_type] ?? "ℹ️"}</span>
                <div className="insight-item__body">
                  <strong>{ins.title}</strong>
                  <p>{ins.description}</p>
                </div>
                <span className={`severity-badge severity-badge--${ins.severity}`}>{ins.severity}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Sub-component                                                      */
/* ------------------------------------------------------------------ */

function MetricCard({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className={`metric-card metric-card--${accent}`}>
      <span className="metric-card__label">{label}</span>
      <span className="metric-card__value">{value}</span>
    </div>
  );
}
