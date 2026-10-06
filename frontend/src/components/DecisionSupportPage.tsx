import { useState } from "react";
import {
  analyzeDecision,
  explainDecision,
  chatDecisionSupport,
  type DecisionAnalyzeResponse,
  type AIExplanationResult,
  type ChatMessage,
  type DecisionChatRequest,
} from "../api/financial";

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const SCENARIO_TYPES = [
  { value: "large_purchase", label: "Large Purchase (one-time)" },
  { value: "recurring_expense_add", label: "Recurring Expense (new monthly)" },
  { value: "income_reduction", label: "Income Reduction (ongoing)" },
  { value: "expense_increase", label: "Expense Increase (ongoing)" },
];

const PERIODS = [
  { value: "current_month", label: "Current Month" },
  { value: "previous_month", label: "Previous Month" },
  { value: "last_3_months", label: "Last 3 Months" },
  { value: "last_6_months", label: "Last 6 Months" },
  { value: "last_12_months", label: "Last 12 Months" },
];

const EXAMPLE_QUESTIONS = [
  "Explain this result in simple words.",
  "Why is this purchase considered high risk?",
  "Why did my savings rate change?",
  "Is my liquidity sufficient for this decision?",
  "Which risk indicator is the most critical?",
];

function fmt(v: string | null | undefined, currency?: string): string {
  if (v === null || v === undefined) return "Unavailable";
  const n = Number(v);
  if (isNaN(n)) return v;
  return currency
    ? `${currency} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(v: string | null | undefined): string {
  if (v === null || v === undefined) return "Unavailable";
  return `${Number(v).toFixed(2)}%`;
}

function statusDot(status: string): string {
  if (status === "available" || status === "sufficient") return "dot--active";
  if (status === "unavailable" || status === "insufficient") return "dot--inactive";
  return "dot--partial";
}

/* ------------------------------------------------------------------ */
/* Component                                                          */
/* ------------------------------------------------------------------ */

export default function DecisionSupportPage() {
  /* Form state */
  const [scenarioType, setScenarioType] = useState("large_purchase");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("LKR");
  const [description, setDescription] = useState("");
  const [period, setPeriod] = useState("last_3_months");

  /* Result state */
  const [result, setResult] = useState<DecisionAnalyzeResponse | null>(null);
  const [aiExplanation, setAiExplanation] = useState<AIExplanationResult | null>(null);
  const [aiStatus, setAiStatus] = useState<string | null>(null);
  const [aiStatusMessage, setAiStatusMessage] = useState<string | null>(null);
  const [aiDisclaimer, setAiDisclaimer] = useState<string | null>(null);

  /* Chat state */
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAnalyze(e: React.FormEvent) {
    e.preventDefault();
    if (!amount || Number(amount) <= 0) { setError("Please enter a positive amount."); return; }
    setLoading(true);
    setError(null);
    setResult(null);
    setAiExplanation(null);
    setAiStatus(null);
    setAiStatusMessage(null);
    setAiDisclaimer(null);
    setChatMessages([]);
    setChatError(null);
    try {
      const res = await analyzeDecision({
        scenario_type: scenarioType,
        amount: Number(amount),
        currency: currency.toUpperCase(),
        description: description || undefined,
        period,
      });
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleExplain() {
    setAiLoading(true);
    setAiExplanation(null);
    setAiStatus(null);
    setAiStatusMessage(null);
    setAiDisclaimer(null);
    try {
      const res = await explainDecision({
        scenario_type: scenarioType,
        amount: Number(amount),
        currency: currency.toUpperCase(),
        description: description || undefined,
        period,
      });
      setResult(res.deterministic_analysis);
      setAiExplanation(res.ai_explanation);
      setAiStatus(res.ai_status);
      setAiStatusMessage(res.ai_status_message);
      setAiDisclaimer(res.disclaimer);
    } catch (e: any) {
      setAiStatus("error");
      setAiStatusMessage(e.message);
    } finally {
      setAiLoading(false);
    }
  }

  async function sendQuestion(questionText: string) {
    if (!questionText.trim() || !result || chatLoading) return;

    const q = questionText.trim();
    const updatedHistory: ChatMessage[] = [...chatMessages, { role: "user", content: q }];
    setChatMessages(updatedHistory);
    setChatInput("");
    setChatLoading(true);
    setChatError(null);

    const payload: DecisionChatRequest = {
      decision_context: {
        scenario_type: scenarioType,
        amount: Number(amount),
        currency: currency.toUpperCase(),
        description: description || undefined,
        period,
      },
      question: q,
      conversation_history: chatMessages,
    };

    try {
      const res = await chatDecisionSupport(payload);
      setChatMessages([...updatedHistory, { role: "assistant", content: res.answer }]);
    } catch (err: any) {
      const fallbackMsg =
        err.message || "AI chat is temporarily unavailable. Your deterministic financial decision result remains valid.";
      setChatMessages([
        ...updatedHistory,
        { role: "assistant", content: `⚠️ ${fallbackMsg}` },
      ]);
      setChatError(fallbackMsg);
    } finally {
      setChatLoading(false);
    }
  }

  function handleChatSubmit(e: React.FormEvent) {
    e.preventDefault();
    sendQuestion(chatInput);
  }

  return (
    <div className="page-content" id="page-decision-support">
      <h1 className="page-title">Decision Support</h1>

      {/* ── Scenario Form ── */}
      <section className="card" id="decision-form">
        <h2 className="card__title">Scenario Configuration</h2>
        <form className="decision-form" onSubmit={handleAnalyze}>
          <div className="form-grid-2">
            <div className="form-group">
              <label className="form-label" htmlFor="ds-scenario-type">Scenario Type</label>
              <select id="ds-scenario-type" className="form-input" value={scenarioType} onChange={(e) => setScenarioType(e.target.value)}>
                {SCENARIO_TYPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="ds-period">Analysis Period</label>
              <select id="ds-period" className="form-input" value={period} onChange={(e) => setPeriod(e.target.value)}>
                {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="ds-amount">Amount</label>
              <input id="ds-amount" className="form-input" type="number" step="0.01" min="0.01" placeholder="e.g. 50000" value={amount} onChange={(e) => setAmount(e.target.value)} required />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="ds-currency">Currency (ISO 4217)</label>
              <input id="ds-currency" className="form-input" type="text" maxLength={3} placeholder="LKR" value={currency} onChange={(e) => setCurrency(e.target.value)} required />
            </div>
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="ds-description">Description (optional)</label>
            <input id="ds-description" className="form-input" type="text" maxLength={255} placeholder="e.g. New laptop purchase" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          {error && <div className="alert-box alert-box--error">{error}</div>}
          <div className="form-actions">
            <button type="submit" className="btn btn--primary" disabled={loading}>
              {loading ? <><span className="btn-spinner" /> Analyzing…</> : "Analyze Scenario"}
            </button>
            {result && (
              <button type="button" className="btn btn--accent" onClick={handleExplain} disabled={aiLoading}>
                {aiLoading ? <><span className="btn-spinner" /> Generating AI Explanation…</> : "🤖 Get AI Explanation"}
              </button>
            )}
          </div>
        </form>
      </section>

      {/* ── AI Explanation ── */}
      {(aiStatus || aiLoading) && (
        <section className="card" id="decision-ai">
          <h2 className="card__title">🤖 AI Explanation</h2>
          {aiLoading && <div className="page-loading"><div className="loading-spinner" /><p>Generating explanation…</p></div>}
          {aiStatus === "success" && aiExplanation ? (
            <div className="ai-result">
              <div className="ai-section">
                <h3>Summary</h3>
                <p>{aiExplanation.summary}</p>
              </div>
              <div className="ai-section">
                <h3>Cash Flow Impact</h3>
                <p>{aiExplanation.cash_flow_impact_narrative}</p>
              </div>
              <div className="ai-section">
                <h3>Liquidity</h3>
                <p>{aiExplanation.liquidity_narrative}</p>
              </div>
              {aiExplanation.key_tradeoffs.length > 0 && (
                <div className="ai-section">
                  <h3>Key Tradeoffs</h3>
                  <ul>{aiExplanation.key_tradeoffs.map((t, i) => <li key={i}>{t}</li>)}</ul>
                </div>
              )}
              {aiExplanation.data_limitations_noted.length > 0 && (
                <div className="ai-section">
                  <h3>Data Limitations</h3>
                  <ul>{aiExplanation.data_limitations_noted.map((d, i) => <li key={i}>{d}</li>)}</ul>
                </div>
              )}
              <p className="text-dim" style={{ fontSize: "0.75rem", marginTop: "1rem" }}>Provider: {aiExplanation.provider} · Model: {aiExplanation.model}</p>
            </div>
          ) : aiStatus && aiStatus !== "success" && !aiLoading ? (
            <div className="ai-fallback">
              <p className="ai-fallback__msg">⚠️ AI explanation unavailable</p>
              <p className="text-dim">{aiStatusMessage}</p>
              <p className="text-dim" style={{ fontSize: "0.78rem" }}>The deterministic analysis below remains fully valid.</p>
            </div>
          ) : null}
          {aiDisclaimer && <p className="disclaimer">{aiDisclaimer}</p>}
        </section>
      )}

      {/* ── Conversational AI Chat (Phase 15) ── */}
      {result && (
        <section className="card" id="decision-chat" style={{ marginTop: "1.5rem" }}>
          <h2 className="card__title">💬 Ask About This Decision</h2>
          <p className="text-dim" style={{ fontSize: "0.85rem", marginBottom: "1rem" }}>
            Ask follow-up questions to understand the risks, cash flow impacts, or tradeoffs of this decision.
          </p>

          {/* Quick example prompt chips */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
            {EXAMPLE_QUESTIONS.map((q, idx) => (
              <button
                key={idx}
                type="button"
                className="btn btn--secondary"
                style={{ fontSize: "0.8rem", padding: "0.3rem 0.6rem" }}
                disabled={chatLoading}
                onClick={() => sendQuestion(q)}
              >
                {q}
              </button>
            ))}
          </div>

          {/* Conversation history */}
          {chatMessages.length > 0 && (
            <div
              className="chat-history"
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "0.75rem",
                marginBottom: "1rem",
                maxHeight: "400px",
                overflowY: "auto",
                paddingRight: "0.5rem",
              }}
            >
              {chatMessages.map((msg, idx) => (
                <div
                  key={idx}
                  style={{
                    alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "85%",
                    padding: "0.75rem 1rem",
                    borderRadius: "8px",
                    backgroundColor: msg.role === "user" ? "var(--color-primary, #3b82f6)" : "var(--color-bg-card-alt, #1f2937)",
                    color: msg.role === "user" ? "#ffffff" : "var(--color-text, #f3f4f6)",
                    fontSize: "0.9rem",
                    lineHeight: "1.4",
                  }}
                >
                  <div style={{ fontSize: "0.75rem", opacity: 0.7, marginBottom: "0.25rem", fontWeight: 600 }}>
                    {msg.role === "user" ? "You" : "AI Assistant"}
                  </div>
                  <div style={{ whiteSpace: "pre-wrap" }}>{msg.content}</div>
                </div>
              ))}
              {chatLoading && (
                <div style={{ alignSelf: "flex-start", padding: "0.5rem 1rem", fontSize: "0.85rem", color: "#9ca3af" }}>
                  <span className="btn-spinner" /> Thinking…
                </div>
              )}
            </div>
          )}

          {/* Chat input form */}
          <form onSubmit={handleChatSubmit} style={{ display: "flex", gap: "0.5rem" }}>
            <input
              type="text"
              className="form-input"
              style={{ flex: 1 }}
              placeholder="Ask a question about this financial decision…"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              disabled={chatLoading}
              id="chat-input-field"
            />
            <button
              type="submit"
              className="btn btn--primary"
              disabled={chatLoading || !chatInput.trim()}
              id="btn-send-chat"
            >
              {chatLoading ? "Sending…" : "Ask"}
            </button>
          </form>

          {chatError && (
            <p className="text-dim" style={{ fontSize: "0.78rem", color: "#f87171", marginTop: "0.5rem" }}>
              {chatError}
            </p>
          )}

          <p className="disclaimer" style={{ marginTop: "0.75rem" }}>
            This AI chat translates deterministic mathematical calculations into natural language. It does not provide financial advice or perform automated transactions. The backend deterministic engine remains the sole source of truth.
          </p>
        </section>
      )}

      {/* ── Deterministic Result ── */}
      {result && <DecisionResult result={result} />}
    </div>
  );
}


/* ------------------------------------------------------------------ */
/* Decision Result Display                                            */
/* ------------------------------------------------------------------ */

function DecisionResult({ result }: { result: DecisionAnalyzeResponse }) {
  const da = result.data_availability;
  const cf = result.cash_flow_projection;
  const liq = result.liquidity_evaluation;
  const cur = result.currency;

  return (
    <>
      {/* Data Availability */}
      <section className="card" id="decision-data-availability">
        <h2 className="card__title">Data Availability</h2>
        <div className="kv-grid">
          <KV label="Overall Status" value={da.overall_status} dot={statusDot(da.overall_status)} />
          <KV label="Transaction Baseline" value={da.transaction_baseline} dot={statusDot(da.transaction_baseline)} />
          <KV label="Liquidity Data" value={da.liquidity_data} dot={statusDot(da.liquidity_data)} />
          <KV label="Simulation Signals" value={da.simulation_signals} dot={statusDot(da.simulation_signals)} />
          <KV label="Transaction Count" value={String(da.transaction_count)} />
          <KV label="Months Analyzed" value={String(da.months_analyzed)} />
        </div>
        {da.notes.length > 0 && (
          <ul className="notes-list">{da.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        )}
      </section>

      {/* Cash Flow Projection */}
      <section className="card" id="decision-cashflow">
        <h2 className="card__title">Cash Flow Projection</h2>
        <div className="cf-comparison">
          <div className="cf-col">
            <h3 className="cf-col__title">Baseline</h3>
            <KV label="Income" value={fmt(cf.baseline_income, cur)} />
            <KV label="Expenses" value={fmt(cf.baseline_expenses, cur)} />
            <KV label="Net Cash Flow" value={fmt(cf.baseline_net_cash_flow, cur)} />
            <KV label="Savings Rate" value={pct(cf.baseline_savings_rate)} />
          </div>
          <div className="cf-divider">→</div>
          <div className="cf-col">
            <h3 className="cf-col__title">Projected</h3>
            <KV label="Income" value={fmt(cf.projected_income, cur)} />
            <KV label="Expenses" value={fmt(cf.projected_expenses, cur)} />
            <KV label="Net Cash Flow" value={fmt(cf.projected_net_cash_flow, cur)} />
            <KV label="Savings Rate" value={pct(cf.projected_savings_rate)} />
          </div>
        </div>
        <div className="kv-grid" style={{ marginTop: "1rem" }}>
          <KV label="Net Cash Flow Change" value={fmt(cf.net_cash_flow_change, cur)} />
          <KV label="Savings Rate Change" value={pct(cf.savings_rate_change)} />
          <KV label="Impact Type" value={cf.is_one_time_impact ? "One-time" : "Recurring"} />
        </div>
        <p className="impact-summary">{cf.impact_summary}</p>
      </section>

      {/* Liquidity */}
      <section className="card" id="decision-liquidity">
        <h2 className="card__title">Liquidity Evaluation</h2>
        <div className="kv-grid">
          <KV label="Status" value={liq.status} dot={statusDot(liq.status)} />
          <KV label="Known Liquid Balance" value={fmt(liq.known_liquid_balance, cur)} />
          <KV label="Projected Balance After" value={fmt(liq.projected_balance_after, cur)} />
          <KV label="Liquidity Coverage Ratio" value={liq.liquidity_coverage_ratio !== null ? `${Number(liq.liquidity_coverage_ratio).toFixed(2)}x` : "Unavailable"} />
          <KV label="Sufficient?" value={liq.is_liquid_balance_sufficient === null ? "Unknown" : liq.is_liquid_balance_sufficient ? "Yes" : "No"} />
        </div>
        <p className="text-muted" style={{ marginTop: "0.75rem" }}>{liq.explanation}</p>
      </section>

      {/* Ratios */}
      {result.ratios.length > 0 && (
        <section className="card" id="decision-ratios">
          <h2 className="card__title">Financial Ratios</h2>
          <div className="compact-table-wrap">
            <table className="data-table">
              <thead><tr><th>Ratio</th><th>Value</th><th>Computable</th><th>Explanation</th></tr></thead>
              <tbody>
                {result.ratios.map((r, i) => (
                  <tr key={i}>
                    <td>{r.name}</td>
                    <td className="mono">{r.value !== null ? r.value : "Unavailable"}</td>
                    <td>{r.is_computable ? "✓" : "✗"}</td>
                    <td className="text-muted">{r.explanation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Evidence */}
      {result.evidence.length > 0 && (
        <section className="card" id="decision-evidence">
          <h2 className="card__title">Evidence</h2>
          <div className="compact-table-wrap">
            <table className="data-table">
              <thead><tr><th>Metric</th><th>Value</th><th>Rule</th><th>Source</th></tr></thead>
              <tbody>
                {result.evidence.map((ev, i) => (
                  <tr key={i}>
                    <td>{ev.metric}</td>
                    <td className="mono">{ev.value} <span className="text-dim">{ev.unit}</span></td>
                    <td className="text-muted">{ev.rule}</td>
                    <td className="tag">{ev.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Risk Indicators */}
      {result.risk_indicators.length > 0 && (
        <section className="card" id="decision-risks">
          <h2 className="card__title">Risk Indicators</h2>
          <div className="risk-list">
            {result.risk_indicators.map((r, i) => (
              <div key={i} className={`risk-item risk-item--${r.severity.toLowerCase()}`}>
                <div className="risk-item__header">
                  <span className={`severity-badge severity-badge--${r.severity.toLowerCase()}`}>{r.severity}</span>
                  <code className="risk-item__code">{r.code}</code>
                </div>
                <p>{r.message}</p>
                <p className="text-dim">Trigger: {r.trigger_value} | Threshold: {r.threshold_value}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Warnings */}
      {result.warnings.length > 0 && (
        <section className="card" id="decision-warnings">
          <h2 className="card__title">⚠️ Warnings</h2>
          <ul className="notes-list">{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </section>
      )}

      {/* Disclaimer */}
      <section className="card" id="decision-disclaimer">
        <p className="disclaimer">{result.disclaimer}</p>
      </section>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* KV Helper                                                          */
/* ------------------------------------------------------------------ */

function KV({ label, value, dot }: { label: string; value: string; dot?: string }) {
  return (
    <div className="kv-item">
      <span className="kv-item__label">{label}</span>
      <span className="kv-item__value">
        {dot && <span className={`dot ${dot}`} />}
        {value}
      </span>
    </div>
  );
}
