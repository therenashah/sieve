"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  endInterview,
  getInterview,
  logInterviewEvent,
  scheduleInterview,
  sendInterviewMessage,
  startInterview,
  uploadInterviewRecording,
} from "@/lib/api";
import type { InterviewStatusResponse, InterviewTurnMessage } from "@/lib/types";

// --- minimal Web Speech API typings (not in the DOM lib) --------------------
interface SpeechResultAlt {
  transcript: string;
}
interface SpeechRecognitionEventLike {
  results: ArrayLike<ArrayLike<SpeechResultAlt>>;
}
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: (e: SpeechRecognitionEventLike) => void;
  onerror: () => void;
  onend: () => void;
  start: () => void;
  stop: () => void;
}
type SRCtor = new () => SpeechRecognitionLike;

type Stage = "loading" | "schedule" | "lobby" | "live" | "ended" | "expired" | "error";

function fmtClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

export default function InterviewRoom({ token }: { token: string }) {
  const [stage, setStage] = useState<Stage>("loading");
  const [info, setInfo] = useState<InterviewStatusResponse | null>(null);
  const [error, setError] = useState("");

  // scheduling
  const [selectedSlot, setSelectedSlot] = useState("");
  const [scheduling, setScheduling] = useState(false);

  // media / lobby
  const [mediaReady, setMediaReady] = useState(false);
  const [mediaError, setMediaError] = useState("");

  // live interview
  const [messages, setMessages] = useState<InterviewTurnMessage[]>([]);
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [listening, setListening] = useState(false);
  const [sttSupported, setSttSupported] = useState(true);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [wrapSoon, setWrapSoon] = useState(false);
  const [starting, setStarting] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const listenBaseRef = useRef("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const endedRef = useRef(false);

  // ---- load status ----------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const data = await getInterview(token);
        setInfo(data);
        setRemaining(data.remaining_seconds);
        if (data.status === "completed") setStage("ended");
        else if (data.status === "expired") setStage("expired");
        else if (data.status === "in_progress") {
          setMessages(data.messages);
          setStage("lobby"); // re-consent to camera before rejoining
        } else if (data.status === "scheduled") setStage("lobby");
        else setStage("schedule");
      } catch {
        setError("This interview link could not be loaded. It may be invalid or expired.");
        setStage("error");
      }
    })();
  }, [token]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ---- proctoring: tab visibility ------------------------------------------
  useEffect(() => {
    if (stage !== "live") return;
    function onVis() {
      logInterviewEvent(token, document.hidden ? "tab_hidden" : "tab_visible").catch(() => {});
    }
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [stage, token]);

  // ---- countdown timer ------------------------------------------------------
  const finishInterview = useCallback(async () => {
    if (endedRef.current) return;
    endedRef.current = true;
    stopRecordingAndUpload();
    stopMedia();
    try {
      const turn = await endInterview(token);
      if (turn.messages.length) setMessages((prev) => [...prev, ...turn.messages]);
    } catch {
      /* ignore */
    }
    setStage("ended");
  }, [token]);

  useEffect(() => {
    if (stage !== "live" || remaining == null) return;
    if (remaining <= 0) {
      finishInterview();
      return;
    }
    const id = setInterval(() => setRemaining((r) => (r == null ? r : r - 1)), 1000);
    return () => clearInterval(id);
  }, [stage, remaining, finishInterview]);

  // ---- media helpers --------------------------------------------------------
  const attachStreamToVideo = useCallback(() => {
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
  }, []);

  async function requestMedia() {
    setMediaError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      streamRef.current = stream;
      setMediaReady(true);
      setTimeout(attachStreamToVideo, 50);
    } catch {
      setMediaError(
        "We couldn't access your camera and microphone. You can still take the interview by typing, but please allow access for the best experience."
      );
      setMediaReady(false);
    }
  }

  function stopMedia() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  function startRecording() {
    if (!info?.store_recording || !streamRef.current) return;
    try {
      const rec = new MediaRecorder(streamRef.current, { mimeType: "video/webm" });
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "video/webm" });
        if (blob.size > 0) uploadInterviewRecording(token, blob).catch(() => {});
      };
      rec.start(2000);
      recorderRef.current = rec;
    } catch {
      /* recording is best-effort */
    }
  }

  function stopRecordingAndUpload() {
    try {
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
    } catch {
      /* ignore */
    }
  }

  // ---- audio playback (Polly, with browser TTS fallback) --------------------
  const playTurn = useCallback(async (turnMessages: InterviewTurnMessage[]) => {
    for (const m of turnMessages) {
      if (m.role !== "assistant") continue;
      setSpeaking(true);
      try {
        if (m.audio_b64) {
          await new Promise<void>((resolve) => {
            const audio = new Audio(`data:audio/mpeg;base64,${m.audio_b64}`);
            audioRef.current = audio;
            audio.onended = () => resolve();
            audio.onerror = () => resolve();
            audio.play().catch(() => resolve());
          });
        } else if (typeof window !== "undefined" && window.speechSynthesis) {
          await new Promise<void>((resolve) => {
            const u = new SpeechSynthesisUtterance(m.content);
            u.onend = () => resolve();
            u.onerror = () => resolve();
            window.speechSynthesis.speak(u);
          });
        }
      } catch {
        /* ignore playback errors */
      }
    }
    setSpeaking(false);
  }, []);

  // ---- STT ------------------------------------------------------------------
  function toggleListening() {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
    const Impl = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!Impl) {
      setSttSupported(false);
      return;
    }
    const rec = new Impl();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = true;
    listenBaseRef.current = answer ? answer + " " : "";
    rec.onresult = (e) => {
      let transcript = "";
      for (let i = 0; i < e.results.length; i++) {
        transcript += e.results[i][0].transcript;
      }
      setAnswer((listenBaseRef.current + transcript).replace(/\s+/g, " ").trimStart());
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recognitionRef.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch {
      setListening(false);
    }
  }

  // ---- actions --------------------------------------------------------------
  async function handleSchedule() {
    if (!selectedSlot) return;
    setScheduling(true);
    try {
      await scheduleInterview(token, selectedSlot);
      const data = await getInterview(token);
      setInfo(data);
      setStage("lobby");
    } catch {
      setError("Couldn't schedule that slot. Please pick another.");
    } finally {
      setScheduling(false);
    }
  }

  async function handleStart() {
    setStarting(true);
    startRecording();
    try {
      const turn = await startInterview(token);
      setMessages(turn.messages);
      setRemaining(turn.remaining_seconds);
      setWrapSoon(turn.should_wrap_up);
      setStage("live");
      playTurn(turn.messages);
    } catch {
      setError("We couldn't start the interview. Please refresh and try again.");
      setStarting(false);
    }
  }

  async function handleSend() {
    const text = answer.trim();
    if (!text || sending || speaking || stage !== "live") return;
    if (listening) recognitionRef.current?.stop();
    setMessages((prev) => [...prev, { role: "candidate", content: text, audio_b64: null }]);
    setAnswer("");
    setSending(true);
    try {
      const turn = await sendInterviewMessage(token, text);
      setMessages((prev) => [...prev, ...turn.messages]);
      setRemaining(turn.remaining_seconds);
      setWrapSoon(turn.should_wrap_up);
      await playTurn(turn.messages);
      if (turn.status === "completed") {
        endedRef.current = true;
        stopRecordingAndUpload();
        stopMedia();
        setStage("ended");
      }
    } catch {
      setError("Something went wrong sending your answer. Please try again.");
    } finally {
      setSending(false);
    }
  }

  // cleanup on unmount
  useEffect(() => {
    return () => {
      stopRecordingAndUpload();
      stopMedia();
      try {
        recognitionRef.current?.stop();
      } catch {
        /* ignore */
      }
    };
  }, []);

  // re-attach preview when entering lobby with a stream
  useEffect(() => {
    if (stage === "lobby" && mediaReady) attachStreamToVideo();
  }, [stage, mediaReady, attachStreamToVideo]);

  // ---- render ---------------------------------------------------------------
  const brand = (
    <div className="brand-mark" style={{ marginBottom: 0 }}>
      <span className="brand-mark-glyph" style={{ width: 30, height: 30, fontSize: "0.85rem" }}>
        S
      </span>
      <span style={{ fontSize: "0.95rem" }}>sieve</span>
    </div>
  );

  if (stage === "loading") {
    return (
      <div className="interview-shell">
        <p className="round-empty">Loading your interview…</p>
      </div>
    );
  }

  if (stage === "error" || stage === "expired") {
    return (
      <div className="interview-shell">
        <div className="interview-card">
          {brand}
          <h1>{stage === "expired" ? "This interview link has expired" : "Interview unavailable"}</h1>
          <p className="page-subtitle">
            {error ||
              "This interview link has expired. Please reach out to your recruiter if you still need to complete this round."}
          </p>
        </div>
      </div>
    );
  }

  if (stage === "ended") {
    return (
      <div className="interview-shell">
        <div className="interview-card">
          {brand}
          <h1>Thank you! 🎉</h1>
          <p className="page-subtitle">
            That&apos;s the end of your interview. Your responses have been recorded for {info?.job_title
              ? `the ${info.job_title} role`
              : "our team"}{" "}
            and our recruiting team will review them and be in touch about next steps. You can close this tab now.
          </p>
        </div>
      </div>
    );
  }

  // scheduling
  if (stage === "schedule") {
    const grouped = groupSlotsByDay(info?.slots ?? []);
    return (
      <div className="interview-shell">
        <div className="interview-card">
          {brand}
          <h1>Schedule your interview</h1>
          <p className="page-subtitle">
            Hi {info?.candidate_name?.split(" ")[0] ?? "there"}! Pick a time in the next week for your{" "}
            {info?.round_name} for the {info?.job_title} role. It takes about {info?.duration_minutes} minutes and
            you&apos;ll speak with our AI interviewer over video.
          </p>
          {error && <div className="alert alert-error">{error}</div>}
          <div className="slot-groups">
            {grouped.map((g) => (
              <div key={g.day} className="slot-group">
                <div className="section-label">{g.day}</div>
                <div className="slot-row">
                  {g.slots.map((s) => (
                    <button
                      key={s.iso}
                      type="button"
                      className={`slot-chip${selectedSlot === s.iso ? " slot-chip-active" : ""}`}
                      onClick={() => setSelectedSlot(s.iso)}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {grouped.length === 0 && <p className="page-subtitle">No slots available — please contact your recruiter.</p>}
          </div>
          <button className="btn btn-primary btn-block" disabled={!selectedSlot || scheduling} onClick={handleSchedule}>
            {scheduling ? "Scheduling…" : "Confirm slot"}
          </button>
        </div>
      </div>
    );
  }

  // lobby / instructions + device check
  if (stage === "lobby") {
    return (
      <div className="interview-shell">
        <div className="interview-card interview-card-wide">
          {brand}
          <h1>You&apos;re about to start your interview</h1>
          <p className="page-subtitle">
            {info?.round_name} · {info?.job_title} · about {info?.duration_minutes} minutes
            {info?.scheduled_at ? ` · scheduled for ${new Date(info.scheduled_at).toLocaleString()}` : ""}
          </p>

          <div className="lobby-grid">
            <div className="lobby-video-wrap">
              <video ref={videoRef} className="lobby-video" muted playsInline />
              {!mediaReady && (
                <div className="lobby-video-placeholder">
                  <p>Camera preview</p>
                  <button className="btn btn-secondary btn-small" onClick={requestMedia}>
                    Enable camera &amp; mic
                  </button>
                </div>
              )}
            </div>

            <div className="lobby-instructions">
              <div className="section-label">Before you begin</div>
              <ul className="interview-tips">
                <li>Find a quiet, well-lit space and keep your camera on.</li>
                <li>The interviewer will speak to you — answer out loud (or type if you prefer).</li>
                <li>You can ask the interviewer to repeat a question at any time.</li>
                <li>Answer naturally; there are no trick questions. The timer keeps things on track.</li>
                {info?.store_recording && <li>This session is recorded for our recruiting team&apos;s review.</li>}
              </ul>
              {info?.instructions && (
                <>
                  <div className="section-label" style={{ marginTop: "0.8rem" }}>
                    What to expect
                  </div>
                  <p className="page-subtitle" style={{ margin: 0 }}>
                    This interview focuses on your real experience and how you think through problems.
                  </p>
                </>
              )}
            </div>
          </div>

          {mediaError && <div className="alert alert-warning">{mediaError}</div>}
          {error && <div className="alert alert-error">{error}</div>}

          <div className="lobby-actions">
            {!mediaReady && !mediaError && (
              <button className="btn btn-secondary" onClick={requestMedia}>
                Enable camera &amp; mic
              </button>
            )}
            <button className="btn btn-primary" onClick={handleStart} disabled={starting}>
              {starting ? "Starting…" : "Start interview"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // live interview
  const inputDisabled = sending || speaking || stage !== "live";
  return (
    <div className="interview-live">
      <div className="interview-topbar">
        {brand}
        <div className="interview-topbar-meta">
          <span>{info?.round_name}</span>
          <span>·</span>
          <span>{info?.job_title}</span>
        </div>
        <div className={`interview-timer${wrapSoon ? " interview-timer-warn" : ""}`}>
          {remaining != null ? `⏱ ${fmtClock(remaining)}` : ""}
        </div>
      </div>

      {wrapSoon && (
        <div className="interview-wrap-banner">Wrapping up soon — the interviewer will finish shortly.</div>
      )}

      <div className="interview-stage">
        <div className="interview-video-col">
          <video ref={videoRef} className="interview-video" muted playsInline />
          <div className={`interviewer-orb${speaking ? " interviewer-orb-speaking" : ""}`}>
            <span>AI</span>
            <small>{speaking ? "Speaking…" : "Listening"}</small>
          </div>
        </div>

        <div className="interview-transcript-col">
          <div className="interview-transcript">
            {messages.map((m, i) => (
              <div key={i} className={`chat-row ${m.role === "candidate" ? "chat-row-user" : ""}`}>
                <div
                  className={`chat-bubble ${m.role === "candidate" ? "chat-bubble-user" : "chat-bubble-assistant"}`}
                >
                  {m.content}
                </div>
              </div>
            ))}
            {speaking && <div className="interview-hint">The interviewer is speaking…</div>}
            <div ref={bottomRef} />
          </div>

          {error && <div className="alert alert-error">{error}</div>}

          <div className="interview-answer">
            <textarea
              className="chat-input interview-answer-input"
              rows={2}
              value={answer}
              placeholder={speaking ? "Please wait for the interviewer to finish…" : "Speak or type your answer…"}
              disabled={inputDisabled}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            <div className="interview-answer-actions">
              {sttSupported && (
                <button
                  type="button"
                  className={`btn btn-secondary${listening ? " btn-danger" : ""}`}
                  onClick={toggleListening}
                  disabled={inputDisabled}
                >
                  {listening ? "◉ Stop" : "🎤 Speak"}
                </button>
              )}
              <button className="btn btn-primary" onClick={handleSend} disabled={inputDisabled || !answer.trim()}>
                {sending ? "Sending…" : "Send answer"}
              </button>
            </div>
          </div>

          <button className="interview-end-link" onClick={finishInterview}>
            End interview
          </button>
        </div>
      </div>
    </div>
  );
}

// group ISO slots by day for the scheduler UI
function groupSlotsByDay(slots: string[]): { day: string; slots: { iso: string; label: string }[] }[] {
  const map = new Map<string, { iso: string; label: string }[]>();
  for (const iso of slots) {
    const d = new Date(iso);
    const day = d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
    const label = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    if (!map.has(day)) map.set(day, []);
    map.get(day)!.push({ iso, label });
  }
  return Array.from(map.entries()).map(([day, s]) => ({ day, slots: s }));
}
