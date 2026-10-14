import { useState, useEffect } from "react";
import {
  fetchProactiveInsights,
  explainProactiveInsight,
  type ProactiveInsight,
} from "../api/proactive";

function severityBadge(severity: string) {
  switch (severity.toUpperCase()) {
    case "HIGH":
      return { label: "High Priority", className: "badge badge--danger" };
    case "MEDIUM":
      return { label: "Medium Priority", className: "badge badge--warning" };
    case "LOW":
      return { label: "Low Priority", className: "badge badge--info" };
    default:
      return { label: "Info", className: "badge badge--neutral" };
  }
}

function fmtCurrency(val: number, currency: string) {
  return `${currency} ${val.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtMetricValue(val: number, metric: string, currency: string) {
  if (metric === "savings_rate") {
    return `${val.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}%`;
  }
  return fmtCurrency(val, currency);
}


export default function ProactiveInsightsCard() {
  const [insights, setInsights] = useState<ProactiveInsight[]>([]);
  const [dataSufficient, setDataSufficient] = useState(true);
  const [insufficiencyReason, setInsufficiencyReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Map of insight ID -> AI explanation text
  const [explanations, setExplanations] = useState<Record<string, string>>({});
  const [loadingAi, setLoadingAi] = useState<Record<string, boolean>>({});

  useEffect(() => {
    loadInsights();
  }, []);

  async function loadInsights() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchProactiveInsights();
      setInsights(res.insights);
      setDataSufficient(res.data_sufficient);
      setInsufficiencyReason(res.data_sufficiency_reason);
    } catch (err: any) {
      setError(err.message || "Failed to load proactive financial insights.");
    } finally {
      setLoading(false);
    }
  }

  async function handleExplain(insightId: string) {
    if (explanations[insightId]) {
      // Toggle off if already fetched
      setExplanations((prev) => {
        const copy = { ...prev };
        delete copy[insightId];
        return copy;
      });
      return;
    }

    setLoadingAi((prev) => ({ ...prev, [insightId]: true }));
    try {
      const res = await explainProactiveInsight(insightId);
      setExplanations((prev) => ({ ...prev, [insightId]: res.explanation }));
    } catch (err: any) {
      setExplanations((prev) => ({
        ...prev,
        [insightId]: `Unable to generate AI explanation: ${err.message}`,
      }));
    } finally {
      setLoadingAi((prev) => ({ ...prev, [insightId]: false }));
    }
  }

  if (loading) {
    return (
      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <h3 style={{ margin: 0, fontSize: "1.1rem" }}>⚡ Proactive Financial Intelligence</h3>
        <p className="text-muted" style={{ marginTop: "0.5rem" }}>Analyzing historical baseline data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card alert alert--danger" style={{ marginBottom: "1.5rem" }}>
        <strong>Proactive Intelligence Error:</strong> {error}
      </div>
    );
  }

  if (!dataSufficient) {
    return (
      <div className="card" style={{ marginBottom: "1.5rem", borderLeft: "4px solid var(--color-warning, #f59e0b)" }}>
        <h3 style={{ margin: 0, fontSize: "1.1rem" }}>⚡ Proactive Financial Intelligence</h3>
        <p className="text-muted" style={{ fontSize: "0.9rem", marginTop: "0.5rem" }}>
          ℹ️ {insufficiencyReason || "More transaction history is needed before baseline trends can be evaluated."}
        </p>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <div>
          <h3 style={{ margin: 0, fontSize: "1.15rem" }}>⚡ Proactive Financial Intelligence</h3>
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>
            Automated trend & risk detection derived from verified baseline metrics
          </span>
        </div>
        <button className="btn btn--small btn--outline" onClick={loadInsights} title="Refresh analysis">
          🔄 Refresh
        </button>
      </div>

      {insights.length === 0 ? (
        <p className="text-muted" style={{ fontSize: "0.9rem" }}>
          ✅ No critical financial variances or unexpected trends detected in your recent baseline.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {insights.map((insight) => {
            const badge = severityBadge(insight.severity);
            const isExplaining = loadingAi[insight.id];
            const explanation = explanations[insight.id];
            const ev = insight.evidence;

            return (
              <div
                key={insight.id}
                className="card"
                style={{
                  padding: "1rem",
                  backgroundColor: "var(--bg-card-alt, #f9fafb)",
                  border: "1px solid var(--border-color, #e5e7eb)",
                }}
              >
                {/* Header */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem" }}>
                  <div>
                    <span className={badge.className} style={{ marginRight: "0.5rem", fontSize: "0.75rem" }}>
                      {badge.label}
                    </span>
                    <span className="badge badge--neutral" style={{ fontSize: "0.75rem" }}>
                      Confidence: {insight.confidence}
                    </span>
                    <h4 style={{ margin: "0.4rem 0 0.2rem 0", fontSize: "1rem" }}>{insight.title}</h4>
                  </div>
                </div>

                <p style={{ fontSize: "0.9rem", color: "var(--text-color, #374151)", margin: "0.4rem 0 0.8rem 0" }}>
                  {insight.description}
                </p>

                {/* Evidence Panel */}
                <div
                  style={{
                    backgroundColor: "#ffffff",
                    padding: "0.75rem 1rem",
                    borderRadius: "6px",
                    border: "1px solid var(--border-color, #e5e7eb)",
                    fontSize: "0.85rem",
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
                    gap: "0.5rem",
                    marginBottom: "0.75rem",
                  }}
                >
                  <div>
                    <span className="text-muted" style={{ display: "block", fontSize: "0.75rem" }}>Current (30 Days)</span>
                    <strong>{fmtMetricValue(ev.current_value, ev.metric, insight.currency)}</strong>
                  </div>
                  <div>
                    <span className="text-muted" style={{ display: "block", fontSize: "0.75rem" }}>Baseline (3 Months)</span>
                    <strong>{fmtMetricValue(ev.baseline_value, ev.metric, insight.currency)}</strong>
                  </div>
                  <div>
                    <span className="text-muted" style={{ display: "block", fontSize: "0.75rem" }}>Variance</span>
                    <strong style={{ color: ev.change_amount > 0 ? (ev.metric === "monthly_expenses" ? "#dc2626" : "#059669") : (ev.metric === "monthly_expenses" ? "#059669" : "#dc2626") }}>
                      {ev.change_amount > 0 ? "+" : ""}{fmtMetricValue(ev.change_amount, ev.metric, insight.currency)}
                      {ev.change_percent !== null && ` (${ev.change_percent > 0 ? "+" : ""}${ev.change_percent}%)`}
                    </strong>
                  </div>
                  <div>
                    <span className="text-muted" style={{ display: "block", fontSize: "0.75rem" }}>Period</span>
                    <span>{ev.period_label}</span>
                  </div>
                </div>

                {/* AI Explanation Toggle */}
                <div>
                  <button
                    className="btn btn--small btn--outline"
                    onClick={() => handleExplain(insight.id)}
                    disabled={isExplaining}
                    style={{ fontSize: "0.8rem" }}
                  >
                    {isExplaining ? "Generating AI Explanation..." : explanation ? "Hide AI Explanation" : "✨ Explain with AI"}
                  </button>

                  {explanation && (
                    <div
                      style={{
                        marginTop: "0.75rem",
                        padding: "0.85rem 1rem",
                        backgroundColor: "rgba(37, 99, 235, 0.05)",
                        borderLeft: "3px solid var(--color-primary, #2563eb)",
                        borderRadius: "4px",
                        fontSize: "0.9rem",
                      }}
                    >
                      <div style={{ fontWeight: 600, fontSize: "0.8rem", color: "var(--color-primary, #2563eb)", marginBottom: "0.3rem" }}>
                        🤖 AI Explanation (Derived from verified evidence)
                      </div>
                      <div style={{ whiteSpace: "pre-wrap" }}>{explanation}</div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
