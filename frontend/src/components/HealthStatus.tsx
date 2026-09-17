/**
 * HealthStatus component — displays backend API and database connectivity status.
 */

import { useCallback, useEffect, useState } from "react";
import { fetchDBHealth, fetchHealth } from "../api/health";
import type { DBHealthResponse, HealthResponse } from "../api/health";

type ConnectionState = "loading" | "connected" | "error";

export default function HealthStatus() {
  const [apiStatus, setApiStatus] = useState<HealthResponse | null>(null);
  const [dbStatus, setDbStatus] = useState<DBHealthResponse | null>(null);
  const [apiState, setApiState] = useState<ConnectionState>("loading");
  const [dbState, setDbState] = useState<ConnectionState>("loading");
  const [refreshing, setRefreshing] = useState(false);

  const loadStatus = useCallback(async () => {
    setRefreshing(true);

    // API health
    try {
      const health = await fetchHealth();
      setApiStatus(health);
      setApiState("connected");
    } catch {
      setApiStatus(null);
      setApiState("error");
    }

    // DB health
    try {
      const dbHealth = await fetchDBHealth();
      setDbStatus(dbHealth);
      setDbState(dbHealth.database === "connected" ? "connected" : "error");
    } catch {
      setDbStatus(null);
      setDbState("error");
    }

    setRefreshing(false);
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const stateColor = (state: ConnectionState) => {
    switch (state) {
      case "connected":
        return "var(--color-success)";
      case "error":
        return "var(--color-danger)";
      default:
        return "var(--color-warning)";
    }
  };

  const stateLabel = (state: ConnectionState) => {
    switch (state) {
      case "connected":
        return "Connected";
      case "error":
        return "Disconnected";
      default:
        return "Checking…";
    }
  };

  return (
    <div className="health-status">
      <div className="health-status__header">
        <h2>System Status</h2>
        <button
          className="health-status__refresh"
          onClick={loadStatus}
          disabled={refreshing}
          title="Refresh status"
          id="btn-refresh-health"
        >
          {refreshing ? "⟳" : "↻"} Refresh
        </button>
      </div>

      <div className="health-status__cards">
        {/* API Card */}
        <div className="status-card" id="status-card-api">
          <div
            className="status-card__indicator"
            style={{ backgroundColor: stateColor(apiState) }}
          />
          <div className="status-card__body">
            <span className="status-card__label">FastAPI Backend</span>
            <span
              className="status-card__value"
              style={{ color: stateColor(apiState) }}
            >
              {stateLabel(apiState)}
            </span>
            {apiStatus && (
              <span className="status-card__detail">
                status: {apiStatus.status}
              </span>
            )}
          </div>
        </div>

        {/* DB Card */}
        <div className="status-card" id="status-card-db">
          <div
            className="status-card__indicator"
            style={{ backgroundColor: stateColor(dbState) }}
          />
          <div className="status-card__body">
            <span className="status-card__label">PostgreSQL Database</span>
            <span
              className="status-card__value"
              style={{ color: stateColor(dbState) }}
            >
              {stateLabel(dbState)}
            </span>
            {dbStatus && (
              <span className="status-card__detail">
                database: {dbStatus.database}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
