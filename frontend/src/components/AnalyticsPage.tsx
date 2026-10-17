import { useEffect, useState, useMemo } from "react";
import {
  fetchAnalyticsSummary,
  fetchAnalyticsMonthly,
  fetchAnalyticsCategories,
  fetchAnalyticsRecurring,
  fetchInsights,
  type AnalyticsSummaryByCurrency,
  type MonthlyDataByCurrency,
  type CategoryBreakdownItem,
  type RecurringTransactionItem,
  type FinancialInsight,
} from "../api/financial";

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

const PERIODS = [
  { value: "current_month", label: "Current Month" },
  { value: "previous_month", label: "Previous Month" },
  { value: "last_3_months", label: "Last 3 Months" },
  { value: "last_6_months", label: "Last 6 Months" },
  { value: "last_12_months", label: "Last 12 Months" },
];

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const INSIGHT_ICONS: Record<string, string> = {
  HIGH_EXPENSE_CATEGORY: "⚠️", EXPENSE_INCREASE: "📈", NEGATIVE_CASH_FLOW: "🔻",
  RECURRING_EXPENSE_DETECTED: "🔄", INCOME_DECREASE: "📉", LARGE_TRANSACTION: "💰",
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

export default function AnalyticsPage() {
  const [period, setPeriod] = useState("last_3_months");
  const [summary, setSummary] = useState<AnalyticsSummaryByCurrency[]>([]);
  const [monthly, setMonthly] = useState<MonthlyDataByCurrency[]>([]);
  const [categories, setCategories] = useState<CategoryBreakdownItem[]>([]);
  const [recurring, setRecurring] = useState<RecurringTransactionItem[]>([]);
  const [insights, setInsights] = useState<FinancialInsight[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshingInsights, setRefreshingInsights] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(p: string, generate: boolean = false) {
    setLoading(true);
    setError(null);
    try {
      const [sum, mon, cat, rec, ins] = await Promise.all([
        fetchAnalyticsSummary(p).then((r) => r.by_currency),
        fetchAnalyticsMonthly(p).then((r) => r.monthly_data),
        fetchAnalyticsCategories(p).then((r) => r.categories),
        fetchAnalyticsRecurring().then((r) => r.detected_patterns),
        fetchInsights(p, generate).then((r) => r.insights),
      ]);
      setSummary(sum);
      setMonthly(mon);
      setCategories(cat);
      setRecurring(rec);
      setInsights(ins);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(period, false); }, [period]);

  async function handleRefreshInsights() {
    setRefreshingInsights(true);
    try {
      const res = await fetchInsights(period, true);
      setInsights(res.insights);
    } catch (e: any) {
      setError(e.message ?? "Failed to refresh insights");
    } finally {
      setRefreshingInsights(false);
    }
  }

  const dedupedInsights = useMemo(() => {
    const seen = new Set<string>();
    return insights.filter((ins) => {
      const meta = (ins.metadata_json || {}) as Record<string, any>;
      const disc = meta.category
        ? `cat:${String(meta.category).trim().toLowerCase()}`
        : meta.transaction_id
        ? `tx:${String(meta.transaction_id).trim().toLowerCase()}`
        : meta.merchant
        ? `mch:${String(meta.merchant).trim().toLowerCase()}`
        : `title:${String(ins.title || '').trim().toLowerCase()}`;
      const ccy = ins.currency ? String(ins.currency).trim().toUpperCase() : "";
      const key = `${ins.insight_type}-${ccy}-${ins.period_start || ""}-${disc}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [insights]);

  if (loading) return <div className="page-loading"><div className="loading-spinner" /><p>Loading analytics…</p></div>;
  if (error) return <div className="alert-box alert-box--error">{error}</div>;

  return (
    <div className="page-content" id="page-analytics">
      <div className="page-header-row">
        <h1 className="page-title">Analytics</h1>
        <select className="form-input form-input--select" value={period} onChange={(e) => setPeriod(e.target.value)} id="analytics-period">
          {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </div>

      {/* ── Summary ── */}
      <section className="card" id="analytics-summary">
        <h2 className="card__title">Financial Summary</h2>
        {summary.length === 0 ? <p className="empty-text">No data for this period.</p> : (
          <div className="metric-grid">
            {summary.map((s) => (
              <div key={s.currency} className="metric-group">
                <span className="metric-group__currency">{s.currency}</span>
                <div className="metric-row">
                  <div className="metric-card metric-card--success"><span className="metric-card__label">Income</span><span className="metric-card__value">{fmt(s.total_income, s.currency)}</span></div>
                  <div className="metric-card metric-card--danger"><span className="metric-card__label">Expenses</span><span className="metric-card__value">{fmt(s.total_expenses, s.currency)}</span></div>
                  <div className={`metric-card metric-card--${Number(s.net_cash_flow) >= 0 ? "success" : "danger"}`}><span className="metric-card__label">Net Cash Flow</span><span className="metric-card__value">{fmt(s.net_cash_flow, s.currency)}</span></div>
                  <div className="metric-card metric-card--primary"><span className="metric-card__label">Savings Rate</span><span className="metric-card__value">{s.savings_rate !== null ? `${Number(s.savings_rate).toFixed(1)}%` : "Unavailable"}</span></div>
                </div>
                <p className="text-dim" style={{ marginTop: "0.5rem", fontSize: "0.82rem" }}>
                  {s.transaction_count} transactions ({s.income_transaction_count} income, {s.expense_transaction_count} expense)
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Monthly Cash Flow ── */}
      <section className="card" id="analytics-monthly">
        <h2 className="card__title">Monthly Cash Flow</h2>
        {monthly.length === 0 ? <p className="empty-text">No monthly data available.</p> : (
          <div className="compact-table-wrap">
            <table className="data-table">
              <thead><tr><th>Month</th><th>Currency</th><th>Income</th><th>Expenses</th><th>Net</th></tr></thead>
              <tbody>
                {monthly.map((m, i) => (
                  <tr key={i}>
                    <td>{MONTH_NAMES[m.month - 1]} {m.year}</td>
                    <td>{m.currency}</td>
                    <td className="mono text-success">{fmt(m.income, m.currency)}</td>
                    <td className="mono text-danger">{fmt(m.expenses, m.currency)}</td>
                    <td className={`mono ${Number(m.net_cash_flow) >= 0 ? "text-success" : "text-danger"}`}>{fmt(m.net_cash_flow, m.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Expense Categories ── */}
      <section className="card" id="analytics-categories">
        <h2 className="card__title">Expense Categories</h2>
        {categories.length === 0 ? <p className="empty-text">No category data available.</p> : (
          <div className="category-list">
            {categories.map((c, i) => (
              <div key={i} className="category-bar-item">
                <div className="category-bar-item__header">
                  <span className="category-bar-item__name">{c.category}</span>
                  <span className="category-bar-item__amount">{fmt(c.amount, c.currency)}</span>
                </div>
                <div className="progress-bar"><div className="progress-bar__fill" style={{ width: `${Math.min(Number(c.percentage), 100)}%` }} /></div>
                <span className="category-bar-item__pct">{Number(c.percentage).toFixed(1)}% · {c.transaction_count} txns</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Recurring Patterns ── */}
      <section className="card" id="analytics-recurring">
        <h2 className="card__title">Recurring Transactions <span className="card__badge">Detected Patterns</span></h2>
        {recurring.length === 0 ? <p className="empty-text">No recurring patterns detected.</p> : (
          <div className="compact-table-wrap">
            <table className="data-table">
              <thead><tr><th>Merchant</th><th>Amount</th><th>Frequency</th><th>Occurrences</th><th>Last Seen</th></tr></thead>
              <tbody>
                {recurring.map((r, i) => (
                  <tr key={i}>
                    <td>{r.merchant}</td>
                    <td className="mono">{fmt(r.approximate_amount, r.currency)}</td>
                    <td className="tag">{r.detected_frequency}</td>
                    <td>{r.occurrence_count}</td>
                    <td className="mono">{r.last_occurrence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Insights ── */}
      <section className="card" id="analytics-insights">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h2 className="card__title" style={{ margin: 0 }}>Financial Insights</h2>
          <button
            id="btn-refresh-analytics-insights"
            className="btn btn--small btn--secondary"
            onClick={handleRefreshInsights}
            disabled={refreshingInsights}
            title="Generate and refresh insights for this period"
          >
            {refreshingInsights ? "Refreshing…" : "🔄 Refresh Insights"}
          </button>
        </div>
        {dedupedInsights.length === 0 ? <p className="empty-text">No insights generated for this period. Click "Refresh Insights" to evaluate your finances.</p> : (
          <div className="insight-list">
            {dedupedInsights.map((ins) => (
              <div key={ins.id} className={`insight-item severity--${ins.severity}`}>
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
