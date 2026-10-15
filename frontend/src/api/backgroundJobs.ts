/**
 * Phase 19 — Background Jobs API client.
 *
 * All requests require session authentication (cookie-based).
 */

import { API_BASE_URL } from "../config";

const API_BASE = `${API_BASE_URL}/api/jobs`;

export type JobType =
  | "ANALYZE_TRANSACTIONS"
  | "GENERATE_INSIGHTS"
  | "DOCUMENT_REPROCESS"
  | "PORTFOLIO_RECALCULATION";

export type JobStatus =
  | "QUEUED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface BackgroundJob {
  id: string;
  job_type: JobType;
  status: JobStatus;
  progress_pct: number;
  progress_message: string | null;
  parameters: Record<string, unknown> | null;
  result_payload: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobSubmitResponse {
  job_id: string;
  job_type: string;
  status: string;
  message: string;
}

export interface JobListResponse {
  jobs: BackgroundJob[];
  total_count: number;
  queued_count: number;
  running_count: number;
  completed_count: number;
  failed_count: number;
}

export interface JobCancelResponse {
  job_id: string;
  status: string;
  message: string;
}

/**
 * Helper to safely process responses, checking Content-Type and status code
 * to prevent exposing 'Unexpected token <' HTML parsing errors.
 */
async function handleResponse<T>(resp: Response, fallbackAction: string): Promise<T> {
  const contentType = resp.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  if (resp.status === 401) {
    throw new Error("Session expired — please log in again.");
  }

  if (!resp.ok) {
    if (isJson) {
      try {
        const err = await resp.json();
        throw new Error(err.detail ?? `${fallbackAction} failed (${resp.status})`);
      } catch (e: any) {
        if (e.message && !e.message.includes("Unexpected token")) {
          throw e;
        }
        throw new Error(`${fallbackAction} failed (${resp.status})`);
      }
    } else {
      if (resp.status === 404) {
        throw new Error("Job endpoint not found (404). Please ensure the backend server is running.");
      }
      throw new Error(`${fallbackAction} failed (${resp.status}): Unexpected response format`);
    }
  }

  if (!isJson) {
    throw new Error("Server returned an unexpected non-JSON response.");
  }

  try {
    return (await resp.json()) as T;
  } catch {
    throw new Error("Failed to parse JSON response from server.");
  }
}

/** Submit a new background job. */
export async function submitJob(
  jobType: JobType,
  parameters?: Record<string, unknown>
): Promise<JobSubmitResponse> {
  const resp = await fetch(API_BASE, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_type: jobType, parameters }),
  });
  return handleResponse<JobSubmitResponse>(resp, "Submit job");
}

/** List all jobs for the authenticated user. */
export async function listJobs(
  statusFilter?: JobStatus
): Promise<JobListResponse> {
  const params = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
  const resp = await fetch(`${API_BASE}${params}`, {
    credentials: "include",
  });
  return handleResponse<JobListResponse>(resp, "List jobs");
}

/** Get a specific job by ID. */
export async function getJob(jobId: string): Promise<BackgroundJob> {
  const resp = await fetch(`${API_BASE}/${jobId}`, {
    credentials: "include",
  });
  return handleResponse<BackgroundJob>(resp, "Get job");
}

/** Cancel a queued or running job. */
export async function cancelJob(jobId: string): Promise<JobCancelResponse> {
  const resp = await fetch(`${API_BASE}/${jobId}/cancel`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return handleResponse<JobCancelResponse>(resp, "Cancel job");
}
