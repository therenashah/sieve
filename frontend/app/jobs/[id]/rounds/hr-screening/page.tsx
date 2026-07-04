"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Leaderboard from "@/components/Leaderboard";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import TriggerScreeningModal from "@/components/TriggerScreeningModal";
import { ApiError, getJob, getLeaderboard } from "@/lib/api";
import type { Job, LeaderboardCandidate, LeaderboardResponse } from "@/lib/types";

function HrScreeningRoundInner() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const router = useRouter();

  const [job, setJob] = useState<Job | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardResponse | null>(null);
  const [error, setError] = useState("");
  const [triggerFor, setTriggerFor] = useState<LeaderboardCandidate | null>(null);

  const refresh = useCallback(() => {
    return Promise.all([getJob(jobId), getLeaderboard(jobId)])
      .then(([j, lb]) => {
        setJob(j);
        setLeaderboard(lb);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/");
          return;
        }
        setError("Couldn't load this round.");
      });
  }, [jobId, router]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <>
      <Navbar />
      <main className="page">
        <button className="link-back" onClick={() => router.push(`/jobs/${jobId}`)}>
          ← {job?.title ?? "Job"}
        </button>

        <div className="page-header">
          <div>
            <h1>Round 2 · HR Screening</h1>
            <p className="page-subtitle">
              Trigger a screening chat per candidate — pick which questions to ask, then share the link.
              Summaries and flags land on each candidate&apos;s page once their chat ends.
            </p>
          </div>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        {leaderboard && leaderboard.candidates.length > 0 && (
          <Leaderboard
            data={leaderboard}
            jobId={jobId}
            onRowClick={(c) => router.push(`/jobs/${jobId}/candidates/${c.id}`)}
            onRefresh={refresh}
            rowAction={{ label: "Trigger HR screening", onClick: (c) => setTriggerFor(c) }}
            readOnly={job?.status === "archived"}
          />
        )}

        {leaderboard && leaderboard.candidates.length === 0 && (
          <div className="empty-state">
            <p>No candidates yet.</p>
          </div>
        )}
      </main>

      {triggerFor && (
        <TriggerScreeningModal
          jobId={jobId}
          candidateId={triggerFor.id}
          candidateName={triggerFor.name}
          onClose={() => setTriggerFor(null)}
        />
      )}
    </>
  );
}

export default function HrScreeningRoundPage() {
  return (
    <RequireAuth>
      <HrScreeningRoundInner />
    </RequireAuth>
  );
}
