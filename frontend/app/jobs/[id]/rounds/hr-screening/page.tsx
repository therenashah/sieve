"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import CandidateTable from "@/components/CandidateTable";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { ApiError, getJob, listCandidates } from "@/lib/api";
import type { Candidate, Job } from "@/lib/types";

function HrScreeningRoundInner() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const router = useRouter();

  const [job, setJob] = useState<Job | null>(null);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getJob(jobId), listCandidates(jobId)])
      .then(([j, c]) => {
        setJob(j);
        setCandidates(c.candidates);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/");
          return;
        }
        setError("Couldn't load this round.");
      });
  }, [jobId, router]);

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

        {candidates && candidates.length > 0 && (
          <CandidateTable
            candidates={candidates}
            showScreeningAction
            onRowClick={(c) => router.push(`/jobs/${jobId}/candidates/${c.id}`)}
          />
        )}

        {candidates && candidates.length === 0 && (
          <div className="empty-state">
            <p>No candidates yet.</p>
          </div>
        )}
      </main>
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
