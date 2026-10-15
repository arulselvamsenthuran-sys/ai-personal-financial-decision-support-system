/**
 * Phase 20 — Monitoring & Notifications API client.
 *
 * All requests require session authentication (cookie-based).
 */

import { API_BASE_URL } from "../config";

const API_BASE = `${API_BASE_URL}/api/monitoring`;

export type FrequencyType = "DAILY" | "WEEKLY";

export interface MonitoringSchedule {
  id: string;
  user_id: string;
  name: string;
  frequency: FrequencyType;
  day_of_week: number | null;
  hour_of_day: number;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
}

export interface MonitoringScheduleCreatePayload {
  name: string;
  frequency: FrequencyType;
  day_of_week?: number | null;
  hour_of_day?: number;
  is_enabled?: boolean;
}

export interface MonitoringScheduleUpdatePayload {
  name?: string;
  frequency?: FrequencyType;
  day_of_week?: number | null;
  hour_of_day?: number;
  is_enabled?: boolean;
}

export interface MonitoringScheduleListResponse {
  schedules: MonitoringSchedule[];
  total_count: number;
}

export interface Notification {
  id: string;
  user_id: string;
  schedule_id: string | null;
  notification_type: string;
  title: string;
  body: string;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  notifications: Notification[];
  total_count: number;
  unread_count: number;
}

export interface UnreadCountResponse {
  unread_count: number;
}

export interface MarkReadResponse {
  success: boolean;
  marked_count: number;
}

async function safeFetch(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("fetch") || msg.includes("Failed") || msg.includes("NetworkError")) {
      throw new Error("Unable to connect to the monitoring service. Please ensure the backend server is running.");
    }
    throw err;
  }
}

async function handleResponse<T>(resp: Response, fallbackAction: string): Promise<T> {
  const contentType = resp.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  if (resp.status === 401) {
    throw new Error("Session expired or authentication required — please log in.");
  }

  if (!resp.ok) {
    if (isJson) {
      try {
        const err = await resp.json();
        throw new Error(err.detail ?? `${fallbackAction} failed (${resp.status})`);
      } catch (e) {
        if (e instanceof Error && e.message !== `${fallbackAction} failed (${resp.status})`) {
          throw e;
        }
        throw new Error(`${fallbackAction} failed with status ${resp.status}`);
      }
    } else {
      if (resp.status === 404) {
        throw new Error("Monitoring endpoint not found (404).");
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


/* ------------------------------------------------------------------ */
/* Schedule Endpoints                                                 */
/* ------------------------------------------------------------------ */

export async function listSchedules(): Promise<MonitoringScheduleListResponse> {
  const resp = await safeFetch(`${API_BASE}/schedules`, {
    credentials: "include",
  });
  return handleResponse<MonitoringScheduleListResponse>(resp, "List schedules");
}

export async function getSchedule(scheduleId: string): Promise<MonitoringSchedule> {
  const resp = await safeFetch(`${API_BASE}/schedules/${scheduleId}`, {
    credentials: "include",
  });
  return handleResponse<MonitoringSchedule>(resp, "Get schedule");
}

export async function createSchedule(
  payload: MonitoringScheduleCreatePayload
): Promise<MonitoringSchedule> {
  const resp = await safeFetch(`${API_BASE}/schedules`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<MonitoringSchedule>(resp, "Create schedule");
}

export async function updateSchedule(
  scheduleId: string,
  payload: MonitoringScheduleUpdatePayload
): Promise<MonitoringSchedule> {
  const resp = await safeFetch(`${API_BASE}/schedules/${scheduleId}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<MonitoringSchedule>(resp, "Update schedule");
}

export async function toggleSchedule(scheduleId: string): Promise<MonitoringSchedule> {
  const resp = await safeFetch(`${API_BASE}/schedules/${scheduleId}/toggle`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<MonitoringSchedule>(resp, "Toggle schedule");
}

export async function deleteSchedule(scheduleId: string): Promise<{ message: string }> {
  const resp = await safeFetch(`${API_BASE}/schedules/${scheduleId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handleResponse<{ message: string }>(resp, "Delete schedule");
}

export async function triggerSchedule(scheduleId: string): Promise<MonitoringSchedule> {
  const resp = await safeFetch(`${API_BASE}/schedules/${scheduleId}/trigger`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<MonitoringSchedule>(resp, "Trigger schedule");
}

/* ------------------------------------------------------------------ */
/* Notification Endpoints                                             */
/* ------------------------------------------------------------------ */

export async function listNotifications(
  isRead?: boolean,
  limit: number = 50,
  offset: number = 0
): Promise<NotificationListResponse> {
  const params = new URLSearchParams();
  if (isRead !== undefined) {
    params.set("is_read", String(isRead));
  }
  params.set("limit", String(limit));
  params.set("offset", String(offset));

  const resp = await safeFetch(`${API_BASE}/notifications?${params.toString()}`, {
    credentials: "include",
  });
  return handleResponse<NotificationListResponse>(resp, "List notifications");
}

export async function getUnreadCount(): Promise<UnreadCountResponse> {
  const resp = await safeFetch(`${API_BASE}/notifications/unread-count`, {
    credentials: "include",
  });
  return handleResponse<UnreadCountResponse>(resp, "Get unread count");
}

export async function markNotificationRead(notificationId: string): Promise<Notification> {
  const resp = await safeFetch(`${API_BASE}/notifications/${notificationId}/read`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<Notification>(resp, "Mark notification as read");
}

export async function markAllNotificationsRead(): Promise<MarkReadResponse> {
  const resp = await safeFetch(`${API_BASE}/notifications/mark-all-read`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<MarkReadResponse>(resp, "Mark all notifications read");
}

export async function deleteNotification(notificationId: string): Promise<{ message: string }> {
  const resp = await safeFetch(`${API_BASE}/notifications/${notificationId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handleResponse<{ message: string }>(resp, "Delete notification");
}

