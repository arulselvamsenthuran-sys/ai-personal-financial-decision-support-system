/**
 * Health API client.
 */

import { API_BASE_URL } from "../config";

export interface HealthResponse {
  status: string;
}

export interface DBHealthResponse {
  status: string;
  database: string;
}

/**
 * Fetch the application health status from GET /api/health.
 */
export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/api/health`);
  if (!res.ok) {
    throw new Error(`Health check failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Fetch the database connectivity status from GET /api/health/db.
 */
export async function fetchDBHealth(): Promise<DBHealthResponse> {
  const res = await fetch(`${API_BASE_URL}/api/health/db`);
  if (!res.ok) {
    throw new Error(`DB health check failed: ${res.status}`);
  }
  return res.json();
}
