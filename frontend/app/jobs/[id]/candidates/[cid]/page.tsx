"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { ApiError, getCandidateDetail, getScreeningAnswers } from "@/lib/api";
import type { CandidateDetail, CandidateRound, ScreeningAnswer, ScreeningSessionSummary } from "@/lib/types";

const ROUND_SUBTITLES: Record<string, string> = {
  resume_screening: "Match score & gate check",
  hr_screening: "Chat summary & updated fitment",
};

const ROUND_EMPTY_HINTS: Record<string, string> = {
  resume_screening:
    "Not run yet — the resume-screening pipeline (mandatory gate + fitment scoring) isn't wired up yet. This card will populate automatically once it is.",
  hr_screening: "No completed HR screening chat yet. Trigger one from the HR Screening round page.",
};

function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function SessionTranscript({
  jobId,
  candidateId,
  session,
}: {
  jobId: string;
  candidateId: string;
  session: ScreeningSessionSummary;
}) {
  const [open, setOpen] = useState(false);
  const [answers, setAnswers] = useState<ScreeningAnswer[] | null>(null);
  const [error, setError] = useState("");

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && answers === null) {
      getScreeningAnswers(jobId, candidateId, session.id)
        .then(setAnswers)
        .catch(() => setError("Couldn't load this transcript."));
    }
  }

  return (
    <div className="transcript-block">
      <button type="button" className="link-back" style={{ margin: 0 }} onClick={toggle}>
        {open ? "▾" : "▸"} Chat completed{" "}
        {session.completed_at ? new Date(session.completed_at).toLocaleString() : ""} — view questions &amp;
        answers
      </button>
      {open && (
        <div className="transcript-qa">
          {error && <div className="alert alert-error">{error}</div>}
          {!answers && !error && <p className="round-empty">Loading…</p>}
          {answers && answers.length === 0 && <p className="round-empty">No answers were captured.</p>}
          {answers &&
            answers.map((a, i) => (
              <div key={i} className="transcript-qa-item">
                <div className="transcript-qa-question">Q: {a.question_text}</div>
                <div className="transcript-qa-answer">A: {a.answer_text}</div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

function RoundCard({
  number,
  title,
  subtitle,
  result,
  emptyHint,
  extra,
}: {
  number: number;
  title: string;
  subtitle: string;
  result: CandidateRound["result"];
  emptyHint: string;
  extra?: React.ReactNode;
}) {
  const redFlags = result?.flags.filter((f) => f.type === "red") ?? [];
  const greenFlags = result?.flags.filter((f) => f.type === "green") ?? [];

  return (
    <div className="card round-detail-card">
      <div className="round-detail-header">
        <div>
          <div className="round-card-subtitle">
            Round {number} · {title}
          </div>
          <div className="round-detail-title">{subtitle}</div>
        </div>
        {result?.score != null && <div className="round-score">{result.score}</div>}
      </div>

      {!result && <p className="round-empty">{emptyHint}</p>}

      {result && (
        <>
          {result.summary && <p style={{ margin: 0 }}>{result.summary}</p>}

          {result.key_highlights.length > 0 && (
            <div>
              <p className="section-label" style={{ margin: "0 0 0.4rem" }}>
                Key highlights
              </p>
              <ul className="highlight-list">
                {result.key_highlights.map((h, i) => (
                  <li key={i}>{h}</li>
                ))}
              </ul>
            </div>
          )}

          {redFlags.length > 0 && (
            <div>
              <p className="section-label" style={{ margin: "0 0 0.4rem", color: "var(--danger-fg)" }}>
                🚩 Red flags
              </p>
              <div className="flag-list">
                {redFlags.map((f, i) => (
                  <div key={i} className="flag-item flag-item-red">
                    <span>{f.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {greenFlags.length > 0 && (
            <div>
              <p className="section-label" style={{ margin: "0 0 0.4rem", color: "var(--success-fg)" }}>
                ✓ Green flags
              </p>
              <div className="flag-list">
                {greenFlags.map((f, i) => (
                  <div key={i} className="flag-item flag-item-green">
                    <span>{f.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <p className="round-card-subtitle" style={{ margin: 0 }}>
            Updated {new Date(result.updated_at).toLocaleString()}
          </p>
        </>
      )}

      {extra}
    </div>
  );
}

function CandidateDetailInner() {
  const params = useParams<{ id: string; cid: string }>();
  const router = useRouter();
  const { id: jobId, cid: candidateId } = params;

  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    getCandidateDetail(jobId, candidateId)
      .then(setCandidate)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/");
          return;
        }
        setError("Couldn't load this candidate.");
      });
  }, [jobId, candidateId, router]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const completedSessions = candidate?.screening_sessions.filter((s) => s.status === "completed") ?? [];

  return (
    <>
      <Navbar />
      <main className="page">
        <button className="link-back" onClick={() => router.push(`/jobs/${jobId}`)}>
          ← Back to job
        </button>

        {error && <div className="alert alert-error">{error}</div>}

        {candidate && (
          <>
            <div className="candidate-header">
              <div className="candidate-avatar">{initials(candidate.name)}</div>
              <div>
                <h1>{candidate.name}</h1>
                <div className="candidate-meta-row">
                  <span>{candidate.email}</span>
                  {candidate.phone && <span>{candidate.phone}</span>}
                  {candidate.external_id && <span>ID {candidate.external_id}</span>}
                  {candidate.application_date && <span>Applied {candidate.application_date}</span>}
                  {candidate.source_type && (
                    <span>
                      {candidate.source_type}
                      {candidate.source_name ? ` · ${candidate.source_name}` : ""}
                    </span>
                  )}
                </div>
              </div>
              <span className="badge badge-neutral" style={{ marginLeft: "auto" }}>
                {candidate.overall_status || "No status"}
              </span>
            </div>

            {candidate.rounds.map((round, i) => (
              <RoundCard
                key={round.round_key}
                number={i + 1}
                title={round.name}
                subtitle={ROUND_SUBTITLES[round.round_key] ?? round.description ?? "AI-assessed round"}
                result={round.result}
                emptyHint={ROUND_EMPTY_HINTS[round.round_key] ?? "Not started yet."}
                extra={
                  round.round_key === "hr_screening" && completedSessions.length > 0 ? (
                    <div>
                      <p className="section-label" style={{ margin: "0.75rem 0 0.4rem" }}>
                        Chat transcripts
                      </p>
                      <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                        {completedSessions.map((s) => (
                          <SessionTranscript key={s.id} jobId={jobId} candidateId={candidateId} session={s} />
                        ))}
                      </div>
                    </div>
                  ) : undefined
                }
              />
            ))}
          </>
        )}
      </main>
    </>
  );
}

export default function CandidatePage() {
  return (
    <RequireAuth>
      <CandidateDetailInner />
    </RequireAuth>
  );
}
