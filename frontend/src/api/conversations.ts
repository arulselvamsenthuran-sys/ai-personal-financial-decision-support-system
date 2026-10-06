/**
 * Conversations API client — Phase 17.
 *
 * All requests use `credentials: "include"` for session cookie authentication.
 * Conversation ownership is strictly enforced by the backend session.
 */

import { API_BASE_URL } from "../config";
import { ApiError } from "./financial";

export interface ConversationSummary {
  id: string;
  title: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationListResponse {
  total_count: number;
  conversations: ConversationSummary[];
}

export interface ConversationMessageItem {
  id: string;
  sequence_number: number;
  role: "user" | "assistant" | "system";
  content: string;
  ai_status?: string | null;
  created_at: string;
}

export interface ConversationDetailResponse {
  conversation_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  total_count: number;
  messages: ConversationMessageItem[];
}

export interface CreateConversationRequest {
  title?: string;
}

export interface SendMessageRequest {
  message: string;
}

export interface SendMessageResponse {
  conversation_id: string;
  user_message: ConversationMessageItem;
  assistant_message: ConversationMessageItem;
  ai_status: string;
  ai_status_message: string;
  disclaimer: string;
}

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${url}`, {
    credentials: "include",
    ...init,
  });
  if (res.status === 401) {
    throw new ApiError("Session expired — please log in again.", 401);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(
      (data as any).detail || `Request failed (${res.status})`,
      res.status
    );
  }
  return data as T;
}

export function createConversation(
  req?: CreateConversationRequest
): Promise<ConversationSummary> {
  return apiFetch("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req || {}),
  });
}

export function fetchConversations(
  limit = 20,
  offset = 0
): Promise<ConversationListResponse> {
  return apiFetch(`/api/conversations?limit=${limit}&offset=${offset}`);
}

export function fetchConversation(
  conversationId: string
): Promise<ConversationDetailResponse> {
  return apiFetch(`/api/conversations/${conversationId}`);
}

export function deleteConversation(conversationId: string): Promise<void> {
  return apiFetch(`/api/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

export function sendMessageToConversation(
  conversationId: string,
  message: string
): Promise<SendMessageResponse> {
  return apiFetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}
