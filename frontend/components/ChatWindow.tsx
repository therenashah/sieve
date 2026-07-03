"use client";

import { useEffect, useRef, useState } from "react";

import { getChatSession, sendChatMessage, startChat } from "@/lib/api";
import type { ChatMessage, SessionStatus } from "@/lib/types";

export default function ChatWindow({ token }: { token: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<SessionStatus | "loading">("loading");
  const [candidateName, setCandidateName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    (async () => {
      try {
        const session = await getChatSession(token);
        setStatus(session.session_status);
        setCandidateName(session.candidate_name);
        setJobTitle(session.job_title);
        if (session.messages.length > 0) {
          setMessages(session.messages);
        } else if (session.session_status === "active") {
          const turn = await startChat(token);
          setMessages(turn.messages);
          setStatus(turn.session_status);
        }
      } catch {
        setError("This screening link could not be loaded. It may be invalid.");
        setStatus("expired");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    const text = input.trim();
    if (!text || sending || status !== "active") return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const turn = await sendChatMessage(token, text);
      setMessages((prev) => [...prev, ...turn.messages]);
      setStatus(turn.session_status);
    } catch {
      setError("Something went wrong sending that message. Please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="chat-shell">
      <div className="chat-header">
        <div className="brand-mark" style={{ marginBottom: 0 }}>
          <span className="brand-mark-glyph" style={{ width: 30, height: 30, fontSize: "0.85rem" }}>
            S
          </span>
          <span style={{ fontSize: "0.95rem" }}>sieve</span>
        </div>
        {jobTitle && (
          <div className="chat-header-meta">
            <span>{candidateName}</span>
            <span>·</span>
            <span>{jobTitle}</span>
          </div>
        )}
      </div>

      <div className="chat-messages">
        {status === "loading" && !error && <p className="round-empty">Loading…</p>}

        {messages.map((message, index) => (
          <div key={index} className={`chat-row ${message.role === "user" ? "chat-row-user" : ""}`}>
            <div className={`chat-bubble ${message.role === "user" ? "chat-bubble-user" : "chat-bubble-assistant"}`}>
              {message.content}
            </div>
          </div>
        ))}

        {status !== "active" && status !== "loading" && (
          <div className="chat-status-banner">
            {status === "completed" ? "This screening chat has ended." : "This screening link has expired."}
          </div>
        )}

        {error && <div className="alert alert-error">{error}</div>}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-row">
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          disabled={status !== "active" || sending}
          placeholder={status === "active" ? "Type your answer…" : "Chat ended"}
        />
        <button
          className="btn btn-primary"
          onClick={handleSend}
          disabled={status !== "active" || sending || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
