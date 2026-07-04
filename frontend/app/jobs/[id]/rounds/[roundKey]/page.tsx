"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Leaderboard from "@/components/Leaderboard";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import TriggerInterviewModal from "@/components/TriggerInterviewModal";
import { ApiError, getJob, getLeaderboard, listRounds } from "@/lib/api";
import type { Job, JobRound, LeaderboardCandidate, LeaderboardResponse } from "@/lib/types";

function InterviewRoundInner() {
  const params = useParams<{ id: string; roundKey: string }>();
  const jobId = params.id;
  const roundKey = params.roundKey;
  const router = useRouter();

  const [job, setJob] = useState<Job | null>(null);
  const [round, setRound] = useState<JobRound | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardResponse | null>(null);
  const [error, setError] = useState("");
  const [triggerFor, setTriggerFor] = useState<LeaderboardCandidate | null>(null);

  const refresh = useCallback(() => {
    return Promise.all([getJob(jobId), listRounds(jobId), getLeaderboard(jobId)])
      .then(([j, rounds, lb]) => {
        setJob(j);
        setRound(rounds.find((r) => r.round_key === roundKey) ?? null);
        setLeaderboard(lb);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/");
          return;
        }
        setError("Couldn't load this round.");
      });
  }, [jobId, roundKey, router]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const cfg = round?.ai_config;

  return (
    <>
      <Navbar />
      <main className="page">
        <button className="link-back" onClick={() => router.push(`/jobs/${jobId}`)}>
          ← {job?.title ?? "Job"}
        </button>

        <div className="page-header">
          <div>
            <h1>{round?.name ?? "AI Interview"}</h1>
            <p className="page-subtitle">
              {round?.is_ai_based
                ? "Generate an interview link per candidate. They schedule a slot within the week and take a live, voice-based interview with the AI interviewer. Scores and summaries land on each candidate's page once the interview ends."
                : "This round isn't configured as an AI interview."}
            </p>
          </div>
        </div>

        {cfg && (
          <div className="card" style={{ marginBottom: "1.25rem" }}>
            <div className="round-detail-header">
              <span className="round-detail-title">Interview setup</span>
            </div>
            <div className="interview-config-grid">
              <div>
                <span className="section-label">Duration</span>
                <div>{cfg.duration_minutes} min</div>
              </div>
              <div>
                <span className="section-label">Difficulty</span>
                <div style={{ textTransform: "capitalize" }}>{cfg.difficulty}</div>
              </div>
              <div>
                <span className="section-label">Recording</span>
                <div>{cfg.store_recording ? "On (video proctored)" : "Off"}</div>
              </div>
              <div>
                <span className="section-label">Candidate Q&amp;A</span>
                <div>{cfg.allow_candidate_questions ? "Allowed" : "Off"}</div>
              </div>
            </div>
            {cfg.focus_areas && (
              <p className="page-subtitle" style={{ marginTop: "0.6rem" }}>
                Focus: {cfg.focus_areas}
              </p>
            )}
          </div>
        )}

        {error && <div className="alert alert-error">{error}</div>}

        {leaderboard && leaderboard.candidates.length > 0 && (
          <Leaderboard
            data={leaderboard}
            jobId={jobId}
            onRowClick={(c) => router.push(`/jobs/${jobId}/candidates/${c.id}`)}
            onRefresh={refresh}
            rowAction={{
              label: "Generate interview link",
              onClick: (c) => setTriggerFor(c),
              disabled: () => !round?.is_ai_based,
            }}
            readOnly={job?.status === "archived"}
          />
        )}

        {leaderboard && leaderboard.candidates.length === 0 && (
          <div className="empty-state">
            <p>No candidates yet.</p>
          </div>
        )}
      </main>

      {triggerFor && round && (
        <TriggerInterviewModal
          jobId={jobId}
          candidateId={triggerFor.id}
          candidateName={triggerFor.name}
          roundKey={roundKey}
          roundName={round.name}
          onClose={() => setTriggerFor(null)}
        />
      )}
    </>
  );
}

export default function InterviewRoundPage() {
  return (
    <RequireAuth>
      <InterviewRoundInner />
    </RequireAuth>
  );
}
