import { useState, useEffect, useMemo, useCallback } from "react";
import {
  fetchProactiveInsights,
  explainProactiveInsight,
  type ProactiveInsight,
} from "../api/proactive";
import {
  fetchInsights,
  type FinancialInsight,
} from "../api/financial";
import { GeminiSparkleIcon, RefreshIcon } from "./Icons";

export default function FinancialInsightsPage() {
  const [proactiveInsights, setProactiveInsights] = useState<ProactiveInsight[]>([]);
  const [ruleInsights, setRuleInsights] = useState<FinancialInsight[]>([]);
  const [dataSufficient, setDataSufficient] = useState(true);
  const [insufficiencyReason, setInsufficiencyReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");

  // AI explanations state (insightId -> explanation markdown)
  const [explanations, setExplanations] = useState<Record<string, string>>({});
  const [loadingAi, setLoadingAi] = useState<Record<string, boolean>>({});

  const loadAllInsights = useCallback(async (triggerGenerate = false) => {
    setLoading(true);
    setError(null);
    try {
      const [proactiveRes, ruleRes] = await Promise.all([
        fetchProactiveInsights().catch(() => ({ insights: [], data_sufficient: true, data_sufficiency_reason: null })),
        fetchInsights("last_3_months", triggerGenerate).catch(() => ({ insights: [], total_count: 0 })),
      ]);
      setProactiveInsights(proactiveRes.insights);
      setDataSufficient(proactiveRes.data_sufficient);
      setInsufficiencyReason(proactiveRes.data_sufficiency_reason);
      setRuleInsights(ruleRes.insights);
    } catch (err: any) {
      setError(err.message || "Failed to load financial insights.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAllInsights();
  }, [loadAllInsights]);

  const handleGenerateFresh = async () => {
    setGenerating(true);
    setError(null);
    try {
      await loadAllInsights(true);
    } finally {
      setGenerating(false);
    }
  };

  const handleExplain = async (insightId: string) => {
    if (explanations[insightId]) {
      // Toggle off if already viewed
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
  };

  // Combine and deduplicate
  const filteredProactive = useMemo(() => {
    if (severityFilter === "ALL") return proactiveInsights;
    return proactiveInsights.filter(
      (ins) => ins.severity.toUpperCase() === severityFilter
    );
  }, [proactiveInsights, severityFilter]);

  const highSeverityCount = useMemo(() => {
    return (
      proactiveInsights.filter((i) => i.severity.toUpperCase() === "HIGH").length +
      ruleInsights.filter((i) => i.severity.toUpperCase() === "HIGH").length
    );
  }, [proactiveInsights, ruleInsights]);

  return (
    <div className="page-content" id="page-financial-insights">
      {/* Page Header */}
      <div className="page-header-row" style={{ marginBottom: "2rem" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
            <h1 className="page-title" style={{ margin: 0 }}>
              AI Financial Insights
            </h1>
            <span className="nav-btn-badge" style={{ fontSize: "0.75rem", padding: "0.2rem 0.6rem" }}>
              New
            </span>
          </div>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.92rem", marginTop: "0.35rem", marginBottom: 0 }}>
            Proactive intelligence, anomaly detection, spending shift alerts, and risk diagnostics.
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <button
            id="btn-generate-fresh-insights"
            className="btn btn--primary"
            onClick={handleGenerateFresh}
            disabled={generating}
            style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}
          >
            {generating ? (
              <>
                <span className="btn-spinner" />
                <span>Evaluating Data…</span>
              </>
            ) : (
              <>
                <GeminiSparkleIcon size={16} />
                <span>Generate Fresh Insights</span>
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert-box alert-box--error" style={{ marginBottom: "1.5rem" }}>
          {error}
        </div>
      )}

      {/* Summary KPI Cards */}
      <div className="metrics-row-4" style={{ marginBottom: "2rem" }}>
        <div className="metric-card-premium">
          <div className="metric-card__label">Total Active Insights</div>
          <div className="metric-card__value" style={{ marginTop: "0.25rem" }}>
            {proactiveInsights.length + ruleInsights.length}
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--color-text-dim)", marginTop: "0.25rem" }}>
            Derived from account transaction history
          </div>
        </div>

        <div className="metric-card-premium">
          <div className="metric-card__label">High Priority Risks</div>
          <div
            className="metric-card__value"
            style={{
              marginTop: "0.25rem",
              color: highSeverityCount > 0 ? "var(--color-danger)" : "var(--color-success)",
            }}
          >
            {highSeverityCount}
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--color-text-dim)", marginTop: "0.25rem" }}>
            {highSeverityCount > 0 ? "Requires review" : "No urgent anomalies detected"}
          </div>
        </div>

        <div className="metric-card-premium">
          <div className="metric-card__label">Proactive Anomaly Alerts</div>
          <div className="metric-card__value" style={{ marginTop: "0.25rem" }}>
            {proactiveInsights.length}
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--color-text-dim)", marginTop: "0.25rem" }}>
            Statistical baseline checks active
          </div>
        </div>

        <div className="metric-card-premium">
          <div className="metric-card__label">AI Explanation Engine</div>
          <div className="metric-card__value" style={{ marginTop: "0.25rem", color: "var(--color-accent)" }}>
            Ready
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--color-text-dim)", marginTop: "0.25rem" }}>
            Powered by Gemini Financial AI
          </div>
        </div>
      </div>

      {/* Filter Tabs */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        {(["ALL", "HIGH", "MEDIUM", "LOW"] as const).map((sev) => (
          <button
            key={sev}
            type="button"
            className={`btn btn--small ${severityFilter === sev ? "btn--primary" : "btn--secondary"}`}
            onClick={() => setSeverityFilter(sev)}
            style={{ borderRadius: "var(--radius-pill)", textTransform: "capitalize" }}
          >
            {sev === "ALL" ? "All Severities" : `${sev.toLowerCase()} Priority`}
          </button>
        ))}
      </div>

      {/* Data Insufficiency Alert */}
      {!dataSufficient && (
        <div
          className="card"
          style={{
            borderLeft: "4px solid var(--color-warning)",
            background: "rgba(245, 158, 11, 0.08)",
            marginBottom: "1.5rem",
          }}
        >
          <div style={{ fontWeight: 600, color: "var(--color-warning)", fontSize: "0.95rem" }}>
            Insufficient Data for Statistical Baseline
          </div>
          <p style={{ fontSize: "0.85rem", color: "var(--color-text-muted)", marginTop: "0.3rem" }}>
            {insufficiencyReason ||
              "At least 5 transactions are required to calculate meaningful statistical baselines and anomaly detection."}
          </p>
        </div>
      )}

      {/* Main Insights List */}
      <section className="card" style={{ marginBottom: "2rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
          <h2 className="card__title" style={{ margin: 0, display: "flex", alignItems: "center", gap: "0.6rem" }}>
            <GeminiSparkleIcon size={20} style={{ color: "var(--color-primary)" }} />
            <span>Proactive Intelligence Feed</span>
          </h2>
          <span style={{ fontSize: "0.82rem", color: "var(--color-text-dim)" }}>
            Showing {filteredProactive.length} item{filteredProactive.length !== 1 ? "s" : ""}
          </span>
        </div>

        {loading ? (
          <div className="page-loading">
            <div className="loading-spinner" />
            <p>Evaluating financial indicators…</p>
          </div>
        ) : filteredProactive.length === 0 ? (
          <div style={{ textAlign: "center", padding: "3rem 1rem", color: "var(--color-text-dim)" }}>
            <p style={{ fontSize: "1rem", fontWeight: 600, color: "var(--color-text)" }}>
              No proactive insights found matching filter.
            </p>
            <p style={{ fontSize: "0.85rem", maxWidth: "450px", margin: "0.5rem auto 1.5rem" }}>
              Your financial metrics are stable, or no anomalies match the selected severity.
            </p>
            <button className="btn btn--secondary" onClick={() => loadAllInsights(true)}>
              <RefreshIcon size={14} style={{ marginRight: "0.4rem" }} />
              Re-evaluate Baseline
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            {filteredProactive.map((ins) => {
              const isExplaining = loadingAi[ins.id];
              const explanation = explanations[ins.id];
              const sevUpper = ins.severity.toUpperCase();

              return (
                <div
                  key={ins.id}
                  className="insight-item-premium"
                  style={{
                    background: "var(--color-surface-alt)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "var(--radius-md)",
                    padding: "1.25rem",
                    transition: "border-color var(--transition)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.35rem" }}>
                        <span
                          className={`severity-badge severity-badge--${sevUpper.toLowerCase()}`}
                          style={{
                            fontSize: "0.72rem",
                            fontWeight: 700,
                            padding: "0.15rem 0.55rem",
                            borderRadius: "var(--radius-pill)",
                          }}
                        >
                          {sevUpper}
                        </span>
                        <span style={{ fontSize: "0.78rem", color: "var(--color-text-dim)" }}>
                          {ins.insight_type.replace(/_/g, " ")}
                        </span>
                      </div>
                      <h3 style={{ fontSize: "1.05rem", fontWeight: 700, margin: "0.2rem 0 0.4rem", color: "var(--color-text)" }}>
                        {ins.title}
                      </h3>
                      <p style={{ fontSize: "0.88rem", color: "var(--color-text-muted)", margin: 0, lineHeight: 1.5 }}>
                        {ins.description}
                      </p>
                    </div>

                    <button
                      type="button"
                      className="btn btn--small btn--secondary"
                      onClick={() => handleExplain(ins.id)}
                      disabled={isExplaining}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.4rem",
                        flexShrink: 0,
                        borderColor: explanation ? "var(--color-primary)" : undefined,
                      }}
                    >
                      <GeminiSparkleIcon size={14} style={{ color: "var(--color-primary)" }} />
                      <span>{isExplaining ? "Explaining…" : explanation ? "Hide AI Explanation" : "Explain with AI"}</span>
                    </button>
                  </div>

                  {/* AI Explanation Box */}
                  {explanation && (
                    <div
                      style={{
                        marginTop: "1rem",
                        padding: "1rem 1.15rem",
                        borderRadius: "var(--radius-sm)",
                        background: "rgba(99, 102, 241, 0.08)",
                        border: "1px solid rgba(99, 102, 241, 0.25)",
                        animation: "fade-up 0.25s ease-out",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "0.4rem",
                          fontWeight: 700,
                          fontSize: "0.82rem",
                          color: "var(--color-accent)",
                          marginBottom: "0.4rem",
                        }}
                      >
                        <GeminiSparkleIcon size={14} />
                        <span>AI Financial Advisory Explanation</span>
                      </div>
                      <p style={{ fontSize: "0.88rem", color: "var(--color-text)", margin: 0, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                        {explanation}
                      </p>
                      <div style={{ marginTop: "0.6rem", fontSize: "0.74rem", color: "var(--color-text-dim)" }}>
                        Verified deterministically · No training on private ledger data
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Rule-Based Historical Insights */}
      {ruleInsights.length > 0 && (
        <section className="card">
          <h2 className="card__title" style={{ marginBottom: "1rem" }}>
            Additional Historical Insights
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {ruleInsights.map((ins) => (
              <div
                key={ins.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "0.85rem 1rem",
                  background: "var(--color-surface-alt)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--color-border-subtle)",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: "0.92rem", color: "var(--color-text)" }}>
                    {ins.title}
                  </div>
                  <div style={{ fontSize: "0.82rem", color: "var(--color-text-muted)", marginTop: "0.15rem" }}>
                    {ins.description}
                  </div>
                </div>
                <span className={`tag tag--${ins.severity.toLowerCase()}`}>
                  {ins.severity}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
