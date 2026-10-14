/**
 * Phase 19 — Background Jobs API client.
 *
 * All requests require session authentication (cookie-based).
 */

const API_BASE = "/api/jobs";

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
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `Submit failed: ${resp.status}`);
  }
  return resp.json();
}

/** List all jobs for the authenticated user. */
export async function listJobs(
  statusFilter?: JobStatus
): Promise<JobListResponse> {
  const params = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
  const resp = await fetch(`${API_BASE}${params}`, {
    credentials: "include",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `List jobs failed: ${resp.status}`);
  }
  return resp.json();
}

/** Get a specific job by ID. */
export async function getJob(jobId: string): Promise<BackgroundJob> {
  const resp = await fetch(`${API_BASE}/${jobId}`, {
    credentials: "include",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `Get job failed: ${resp.status}`);
  }
  return resp.json();
}

/** Cancel a queued or running job. */
export async function cancelJob(jobId: string): Promise<JobCancelResponse> {
  const resp = await fetch(`${API_BASE}/${jobId}/cancel`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `Cancel failed: ${resp.status}`);
  }
  return resp.json();
}
