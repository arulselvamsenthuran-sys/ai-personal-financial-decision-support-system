import { useState, useEffect } from "react";
import {
  createConversation,
  fetchConversations,
  fetchConversation,
  deleteConversation,
  sendMessageToConversation,
  type ConversationSummary,
  type ConversationMessageItem,
} from "../api/conversations";

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessageItem[]>([]);
  const [activeTitle, setActiveTitle] = useState<string>("New Conversation");

  const [inputMessage, setInputMessage] = useState("");
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  useEffect(() => {
    loadConversations();
  }, []);

  async function loadConversations() {
    setLoadingList(true);
    setError(null);
    try {
      const res = await fetchConversations();
      setConversations(res.conversations);
      if (res.conversations.length > 0 && !activeConvId) {
        selectConversation(res.conversations[0].id);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load conversations");
    } finally {
      setLoadingList(false);
    }
  }

  async function selectConversation(convId: string) {
    setActiveConvId(convId);
    setLoadingDetail(true);
    setError(null);
    setStatusMessage(null);
    try {
      const detail = await fetchConversation(convId);
      setMessages(detail.messages);
      setActiveTitle(detail.title || "Financial Conversation");
    } catch (err: any) {
      setError(err.message || "Failed to load conversation history");
    } finally {
      setLoadingDetail(false);
    }
  }

  async function handleNewConversation() {
    setError(null);
    try {
      const newConv = await createConversation();
      setConversations((prev) => [newConv, ...prev]);
      setActiveConvId(newConv.id);
      setMessages([]);
      setActiveTitle("New Financial Conversation");
    } catch (err: any) {
      setError(err.message || "Failed to create conversation");
    }
  }

  async function handleDeleteConversation(convId: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!window.confirm("Delete this conversation?")) return;
    try {
      await deleteConversation(convId);
      const updated = conversations.filter((c) => c.id !== convId);
      setConversations(updated);
      if (activeConvId === convId) {
        if (updated.length > 0) {
          selectConversation(updated[0].id);
        } else {
          setActiveConvId(null);
          setMessages([]);
          setActiveTitle("New Conversation");
        }
      }
    } catch (err: any) {
      setError(err.message || "Failed to delete conversation");
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!inputMessage.trim()) return;

    let convId = activeConvId;
    setError(null);
    setStatusMessage(null);
    setSending(true);

    try {
      // Auto-create conversation if none selected
      if (!convId) {
        const newConv = await createConversation();
        convId = newConv.id;
        setActiveConvId(convId);
        setConversations((prev) => [newConv, ...prev]);
      }

      const messageText = inputMessage.trim();
      setInputMessage("");

      // Optimistic user message render
      const tempUserMsg: ConversationMessageItem = {
        id: `temp-${Date.now()}`,
        sequence_number: messages.length + 1,
        role: "user",
        content: messageText,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, tempUserMsg]);

      const res = await sendMessageToConversation(convId, messageText);

      // Replace temp with server responses
      setMessages((prev) => {
        const filtered = prev.filter((m) => !m.id.startsWith("temp-"));
        return [...filtered, res.user_message, res.assistant_message];
      });

      if (res.ai_status !== "success") {
        setStatusMessage(`${res.ai_status_message} (${res.ai_status})`);
      }

      // Refresh list to update message counts & titles
      fetchConversations().then((r) => setConversations(r.conversations));
    } catch (err: any) {
      setError(err.message || "Failed to send message");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="conversations-layout" style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "1.5rem", minHeight: "70vh" }}>
      {/* Sidebar / Conversation List */}
      <aside className="card" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0, fontSize: "1.1rem" }}>Conversations</h3>
          <button
            className="btn btn--small btn--primary"
            onClick={handleNewConversation}
            id="btn-new-conversation"
          >
            + New
          </button>
        </div>

        {loadingList ? (
          <p className="text-muted">Loading history...</p>
        ) : conversations.length === 0 ? (
          <p className="text-muted" style={{ fontSize: "0.9rem" }}>No previous conversations.</p>
        ) : (
          <div className="conversation-list" style={{ display: "flex", flexDirection: "column", gap: "0.5rem", overflowY: "auto", maxHeight: "60vh" }}>
            {conversations.map((c) => (
              <div
                key={c.id}
                onClick={() => selectConversation(c.id)}
                className={`card ${activeConvId === c.id ? "card--active" : ""}`}
                style={{
                  padding: "0.75rem",
                  cursor: "pointer",
                  borderLeft: activeConvId === c.id ? "3px solid var(--color-primary, #2563eb)" : "3px solid transparent",
                  backgroundColor: activeConvId === c.id ? "rgba(37, 99, 235, 0.08)" : "transparent",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center"
                }}
              >
                <div style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                  <div style={{ fontWeight: 600, fontSize: "0.9rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {c.title || "Financial Conversation"}
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.75rem" }}>
                    {c.message_count} messages
                  </div>
                </div>
                <button
                  className="btn btn--small btn--danger"
                  style={{ padding: "2px 6px", fontSize: "0.7rem" }}
                  onClick={(e) => handleDeleteConversation(c.id, e)}
                  title="Delete conversation"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </aside>

      {/* Main Chat Area */}
      <main className="card" style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <div>
          <header style={{ borderBottom: "1px solid var(--border-color, #e5e7eb)", paddingBottom: "0.75rem", marginBottom: "1rem" }}>
            <h2 style={{ margin: 0, fontSize: "1.25rem" }}>{activeTitle}</h2>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>
              Persistent AI Financial Assistant • Historical data isolated & safe
            </span>
          </header>

          {error && (
            <div className="alert alert--danger" style={{ marginBottom: "1rem" }}>
              {error}
            </div>
          )}

          {statusMessage && (
            <div className="alert alert--warning" style={{ marginBottom: "1rem", fontSize: "0.85rem" }}>
              ℹ️ {statusMessage}
            </div>
          )}

          {/* Messages Feed */}
          <div className="chat-feed" style={{ display: "flex", flexDirection: "column", gap: "1rem", minHeight: "350px", maxHeight: "500px", overflowY: "auto", paddingRight: "0.5rem" }}>
            {loadingDetail ? (
              <p className="text-muted">Loading messages...</p>
            ) : messages.length === 0 ? (
              <div style={{ textAlign: "center", color: "var(--text-muted, #6b7280)", marginTop: "4rem" }}>
                <p style={{ fontSize: "1.1rem" }}>💬 Start a new conversation</p>
                <p style={{ fontSize: "0.85rem" }}>Ask questions about your finances, budget, or spending patterns.</p>
              </div>
            ) : (
              messages.map((m) => (
                <div
                  key={m.id}
                  style={{
                    alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "80%",
                    padding: "0.85rem 1.1rem",
                    borderRadius: m.role === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                    backgroundColor: m.role === "user" ? "var(--color-primary, #2563eb)" : "var(--bg-card-alt, #f3f4f6)",
                    color: m.role === "user" ? "#ffffff" : "var(--text-color, #1f2937)",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.1)"
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: "0.75rem", marginBottom: "0.25rem", opacity: 0.8 }}>
                    {m.role === "user" ? "You" : "AI Financial Assistant"}
                  </div>
                  <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "0.95rem" }}>
                    {m.content}
                  </div>
                  {m.ai_status && m.ai_status !== "success" && (
                    <div style={{ fontSize: "0.75rem", marginTop: "0.5rem", fontStyle: "italic", opacity: 0.85 }}>
                      Status: {m.ai_status}
                    </div>
                  )}
                </div>
              ))
            )}
            {sending && (
              <div style={{ alignSelf: "flex-start", padding: "0.75rem 1rem", backgroundColor: "var(--bg-card-alt, #f3f4f6)", borderRadius: "12px" }}>
                <span className="text-muted" style={{ fontSize: "0.9rem" }}>AI is thinking...</span>
              </div>
            )}
          </div>
        </div>

        {/* Input Form */}
        <form onSubmit={handleSend} style={{ marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid var(--border-color, #e5e7eb)", display: "flex", gap: "0.75rem" }}>
          <input
            type="text"
            className="input"
            placeholder="Ask your financial assistant..."
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            disabled={sending}
            style={{ flex: 1 }}
            id="chat-input-message"
          />
          <button
            type="submit"
            className="btn btn--primary"
            disabled={sending || !inputMessage.trim()}
            id="btn-send-message"
          >
            {sending ? "Sending..." : "Send"}
          </button>
        </form>
      </main>
    </div>
  );
}
