"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import TriggerInterviewModal from "@/components/TriggerInterviewModal";
import { ApiError, getJob, listCandidates, listRounds } from "@/lib/api";
import type { Candidate, Job, JobRound } from "@/lib/types";

function InterviewRoundInner() {
  const params = useParams<{ id: string; roundKey: string }>();
  const jobId = params.id;
  const roundKey = params.roundKey;
  const router = useRouter();

  const [job, setJob] = useState<Job | null>(null);
  const [round, setRound] = useState<JobRound | null>(null);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [error, setError] = useState("");
  const [triggerFor, setTriggerFor] = useState<Candidate | null>(null);

  useEffect(() => {
    Promise.all([getJob(jobId), listRounds(jobId), listCandidates(jobId)])
      .then(([j, rounds, c]) => {
        setJob(j);
        setRound(rounds.find((r) => r.round_key === roundKey) ?? null);
        setCandidates(c.candidates);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/");
          return;
        }
        setError("Couldn't load this round.");
      });
  }, [jobId, roundKey, router]);

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

        {candidates && candidates.length > 0 && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>ID</th>
                  <th>Match score</th>
                  <th>Resume</th>
                  <th>{round?.name ?? "Interview"}</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => router.push(`/jobs/${jobId}/candidates/${c.id}`)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>
                      <div className="cand-name">{c.name}</div>
                      <div className="cand-email">{c.email}</div>
                    </td>
                    <td>{c.external_id ?? "—"}</td>
                    <td>{c.match_score != null ? c.match_score : "—"}</td>
                    <td>
                      {c.resume_path ? (
                        <span className="badge badge-success">On file</span>
                      ) : (
                        <span className="badge badge-warning">Missing</span>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <button
                        className="btn btn-small btn-primary"
                        disabled={!round?.is_ai_based}
                        onClick={() => setTriggerFor(c)}
                      >
                        Generate interview link
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {candidates && candidates.length === 0 && (
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
