"use client";

import { useEffect, useRef, useState } from "react";
import { getChatSession, sendChatMessage, startChat } from "@/lib/api";
import type { ChatMessage, SessionStatus } from "@/lib/types";

export default function ChatWindow({ token }: { token: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<SessionStatus | "loading">("loading");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    (async () => {
      try {
        const session = await getChatSession(token);
        setStatus(session.session_status);
        if (session.messages.length > 0) {
          setMessages(session.messages);
        } else if (session.session_status === "active") {
          const turn = await startChat(token);
          setMessages(turn.messages);
          setStatus(turn.session_status);
        }
      } catch {
        setError("This screening link could not be loaded. It may be invalid.");
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
    <div style={{ display: "flex", flexDirection: "column", height: "70vh", border: "1px solid #3333", borderRadius: 8 }}>
      <div style={{ flex: 1, overflowY: "auto", padding: "1rem" }}>
        {messages.map((message, index) => (
          <div
            key={index}
            style={{
              display: "flex",
              justifyContent: message.role === "user" ? "flex-end" : "flex-start",
              marginBottom: "0.75rem",
            }}
          >
            <div
              style={{
                maxWidth: "75%",
                padding: "0.6rem 0.9rem",
                borderRadius: 12,
                background: message.role === "user" ? "#2563eb" : "#3333",
                color: message.role === "user" ? "white" : "inherit",
              }}
            >
              {message.content}
            </div>
          </div>
        ))}
        {status !== "active" && status !== "loading" && (
          <p style={{ textAlign: "center", opacity: 0.7, marginTop: "1rem" }}>
            {status === "completed" ? "This screening chat has ended." : "This screening link has expired."}
          </p>
        )}
        {error && <p style={{ color: "#dc2626" }}>{error}</p>}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: "flex", gap: "0.5rem", padding: "0.75rem", borderTop: "1px solid #3333" }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          disabled={status !== "active" || sending}
          placeholder={status === "active" ? "Type your answer…" : "Chat ended"}
          style={{ flex: 1, padding: "0.6rem", borderRadius: 8, border: "1px solid #3333" }}
        />
        <button
          onClick={handleSend}
          disabled={status !== "active" || sending || !input.trim()}
          style={{ padding: "0.6rem 1.2rem", borderRadius: 8 }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
