"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import {
  ApiError,
  getCandidateDetail,
  getCandidateResume,
  getInterviewSessionDetail,
  getScreeningAnswers,
  interviewRecordingUrl,
  listInterviewSessions,
} from "@/lib/api";
import { statusBadgeClass } from "@/lib/status";
import type {
  CandidateDetail,
  CandidateRound,
  InterviewSessionDetail,
  InterviewSessionSummary,
  ResumeScreeningCriterionScore,
  ScreeningAnswer,
  ScreeningSessionSummary,
} from "@/lib/types";

// A criterion is "working" at 6/10 or above — matches the 3/6/9 anchor convention
// the rubric-generation prompt itself uses (6 = solid/production-level evidence).
const CRITERION_PASS_THRESHOLD = 6;

function CriterionScoreRow({
  criterion,
  tone,
}: {
  criterion: ResumeScreeningCriterionScore;
  tone: "green" | "red";
}) {
  return (
    <div className={`criterion-score-row criterion-score-row-${tone}`}>
      <div className="criterion-score-row-top">
        <span className="criterion-score-row-name">{criterion.name}</span>
        <span className={`score-pill ${tone === "green" ? "score-high" : "score-low"}`}>
          {criterion.score}/10
        </span>
      </div>
      <p className="criterion-score-row-evidence">
        {criterion.evidence === "not found" ? (
          <em>No evidence found in the resume.</em>
        ) : (
          `"${criterion.evidence}"`
        )}
      </p>
      {criterion.note && <p className="criterion-score-row-note">{criterion.note}</p>}
    </div>
  );
}

function ResumeScoringBreakdown({ criteria }: { criteria: ResumeScreeningCriterionScore[] }) {
  if (criteria.length === 0) return null;

  const strengths = [...criteria]
    .filter((c) => c.score >= CRITERION_PASS_THRESHOLD)
    .sort((a, b) => b.score - a.score);
  const weaknesses = [...criteria]
    .filter((c) => c.score < CRITERION_PASS_THRESHOLD)
    .sort((a, b) => a.score - b.score);

  return (
    <div>
      <p className="section-label" style={{ margin: "0.75rem 0 0.4rem" }}>
        Scoring breakdown by criterion
      </p>
      <div className="criteria-breakdown-grid">
        <div className="criteria-breakdown-col criteria-breakdown-col-green">
          <p className="criteria-breakdown-col-title criteria-breakdown-col-title-green">
            ✓ Works well ({strengths.length})
          </p>
          {strengths.length === 0 && <p className="round-empty">Nothing scored {CRITERION_PASS_THRESHOLD}+ yet.</p>}
          {strengths.map((c) => (
            <CriterionScoreRow key={c.criterion_id} criterion={c} tone="green" />
          ))}
        </div>
        <div className="criteria-breakdown-col criteria-breakdown-col-red">
          <p className="criteria-breakdown-col-title criteria-breakdown-col-title-red">
            ✕ Needs work ({weaknesses.length})
          </p>
          {weaknesses.length === 0 && <p className="round-empty">No weak criteria — clean sheet.</p>}
          {weaknesses.map((c) => (
            <CriterionScoreRow key={c.criterion_id} criterion={c} tone="red" />
          ))}
        </div>
      </div>
    </div>
  );
}

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

function InterviewSessionBlock({
  jobId,
  candidateId,
  session,
}: {
  jobId: string;
  candidateId: string;
  session: InterviewSessionSummary;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<InterviewSessionDetail | null>(null);
  const [error, setError] = useState("");

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && detail === null) {
      getInterviewSessionDetail(jobId, candidateId, session.id)
        .then(setDetail)
        .catch(() => setError("Couldn't load this interview."));
    }
  }

  const label =
    session.status === "completed"
      ? `Interview completed ${session.completed_at ? new Date(session.completed_at).toLocaleString() : ""}`
      : `Interview ${session.status}${session.scheduled_at ? ` · ${new Date(session.scheduled_at).toLocaleString()}` : ""}`;

  return (
    <div className="transcript-block">
      <button type="button" className="link-back" style={{ margin: 0 }} onClick={toggle}>
        {open ? "▾" : "▸"} {label} — view transcript &amp; scorecard
      </button>
      {open && (
        <div className="transcript-qa">
          {error && <div className="alert alert-error">{error}</div>}
          {!detail && !error && <p className="round-empty">Loading…</p>}
          {detail && (
            <>
              {detail.scorecard?.recommendation && (
                <p className="round-card-subtitle" style={{ margin: "0 0 0.5rem" }}>
                  Recommendation: <strong>{detail.scorecard.recommendation.replace(/_/g, " ")}</strong>
                  {detail.has_recording && (
                    <>
                      {" · "}
                      <a href={interviewRecordingUrl(jobId, candidateId, detail.id)} target="_blank" rel="noreferrer">
                        ▶ recording
                      </a>
                    </>
                  )}
                </p>
              )}

              {detail.scorecard?.competencies && detail.scorecard.competencies.length > 0 && (
                <div style={{ marginBottom: "0.6rem" }}>
                  {detail.scorecard.competencies.map((c, i) => (
                    <div key={i} className="transcript-qa-item">
                      <div className="transcript-qa-question">
                        {c.name} — {c.rating}/5
                      </div>
                      <div className="transcript-qa-answer">{c.comment}</div>
                    </div>
                  ))}
                </div>
              )}

              {detail.events.length > 0 && (
                <p className="round-card-subtitle" style={{ margin: "0 0 0.5rem", color: "var(--warning-fg)" }}>
                  Proctoring: {detail.events.map((e) => e.type).join(", ")}
                </p>
              )}

              {detail.transcript.map((m, i) => (
                <div key={i} className="transcript-qa-item">
                  <div className="transcript-qa-question">
                    {m.role === "assistant" ? "Interviewer" : "Candidate"}:
                  </div>
                  <div className="transcript-qa-answer">{m.content}</div>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function InterviewReview({
  jobId,
  candidateId,
  roundKey,
}: {
  jobId: string;
  candidateId: string;
  roundKey: string;
}) {
  const [sessions, setSessions] = useState<InterviewSessionSummary[] | null>(null);

  useEffect(() => {
    listInterviewSessions(jobId, candidateId, roundKey)
      .then(setSessions)
      .catch(() => setSessions([]));
  }, [jobId, candidateId, roundKey]);

  if (!sessions || sessions.length === 0) return null;
  return (
    <div>
      <p className="section-label" style={{ margin: "0.75rem 0 0.4rem" }}>
        Interview sessions
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
        {sessions.map((s) => (
          <InterviewSessionBlock key={s.id} jobId={jobId} candidateId={candidateId} session={s} />
        ))}
      </div>
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
  const [resumeLoading, setResumeLoading] = useState(false);

  async function handleViewResume() {
    setResumeLoading(true);
    setError("");
    try {
      const { blob } = await getCandidateResume(jobId, candidateId);
      window.open(URL.createObjectURL(blob), "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't open this candidate's resume.");
    } finally {
      setResumeLoading(false);
    }
  }

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
              <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "0.75rem" }}>
                {candidate.resume_path && (
                  <button className="btn btn-small btn-secondary" onClick={handleViewResume} disabled={resumeLoading}>
                    {resumeLoading ? "Opening…" : "View resume"}
                  </button>
                )}
                <span className={`badge ${statusBadgeClass(candidate.pipeline_status)}`}>
                  {candidate.pipeline_status}
                </span>
              </div>
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
                  round.round_key === "resume_screening" && round.result?.criteria ? (
                    <>
                      {candidate.is_overqualified && (
                        <div className="overqualified-callout">
                          <span>⚠️</span>
                          <div>
                            <strong>Possibly overqualified</strong>
                            {candidate.overqualification_reason ||
                              "Recent experience reads more senior than this role — still ranked on merit, just flagged for review."}
                          </div>
                        </div>
                      )}
                      <ResumeScoringBreakdown criteria={round.result.criteria} />
                    </>
                  ) : round.round_key === "hr_screening" && completedSessions.length > 0 ? (
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
                  ) : round.is_ai_based ? (
                    <InterviewReview jobId={jobId} candidateId={candidateId} roundKey={round.round_key} />
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
