"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import FileUpload from "@/components/FileUpload";
import FunnelChart from "@/components/FunnelChart";
import Leaderboard from "@/components/Leaderboard";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import RoundManagement from "@/components/RoundManagement";
import { ApiError, getJob, getLeaderboard, uploadCvs, uploadTracker } from "@/lib/api";
import type { CvUploadResult, Job, LeaderboardResponse, RowError } from "@/lib/types";

function JobDetailInner() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const router = useRouter();

  const [job, setJob] = useState<Job | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardResponse | null>(null);
  const [error, setError] = useState("");
  const [rowErrors, setRowErrors] = useState<RowError[]>([]);
  const [cvResult, setCvResult] = useState<CvUploadResult | null>(null);

  const refresh = useCallback(() => {
    Promise.all([getJob(jobId), getLeaderboard(jobId)])
      .then(([j, lb]) => {
        setJob(j);
        setLeaderboard(lb);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/");
          return;
        }
        setError("Couldn't load this job posting.");
      });
  }, [jobId, router]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleTrackerUpload(file: File) {
    const result = await uploadTracker(jobId, file);
    setRowErrors(result.row_errors);
    refresh();
  }

  async function handleCvUpload(file: File) {
    const result = await uploadCvs(jobId, file);
    setCvResult(result);
    refresh();
  }

  return (
    <>
      <Navbar />
      <main className="page">
        <button className="link-back" onClick={() => router.push("/jobs")}>
          ← All postings
        </button>

        {error && <div className="alert alert-error">{error}</div>}

        {job && (
          <div className="page-header">
            <div>
              <h1>{job.title}</h1>
              <p className="page-subtitle">{job.description || "No description provided."}</p>
            </div>
            <span className={`badge badge-${job.status}`}>{job.status}</span>
          </div>
        )}

        <div className="card" style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 260px" }}>
            <FileUpload
              accept=".csv,.xlsx,.xls"
              label="Upload / update candidate tracker"
              hint="Adds new candidates or refreshes existing ones by Candidate ID."
              onUpload={handleTrackerUpload}
            />
          </div>
          <div style={{ flex: "1 1 260px" }}>
            <FileUpload
              accept=".zip"
              label="Upload / update candidate CVs (.zip)"
              hint="Matches filenames to candidate names automatically."
              onUpload={handleCvUpload}
            />
          </div>
        </div>

        {rowErrors.length > 0 && (
          <div className="alert alert-warning">
            <strong>{rowErrors.length} tracker row(s) couldn&apos;t be imported:</strong>
            <ul>
              {rowErrors.slice(0, 8).map((e, i) => (
                <li key={i}>
                  Row {e.row}: {e.reason}
                </li>
              ))}
            </ul>
          </div>
        )}

        {cvResult && (
          <>
            <div className="alert alert-success">
              Matched {cvResult.matched.length} of {cvResult.total_candidates} candidates to a CV.
            </div>
            {cvResult.unmatched_candidates.length > 0 && (
              <div className="alert alert-warning">
                <strong>{cvResult.unmatched_candidates.length} candidate(s) have no matching CV:</strong>{" "}
                {cvResult.unmatched_candidates.map((c) => c.name).join(", ")}
              </div>
            )}
            {cvResult.unmatched_files.length > 0 && (
              <div className="alert alert-warning">
                <strong>{cvResult.unmatched_files.length} file(s) couldn&apos;t be matched and were dropped:</strong>{" "}
                {cvResult.unmatched_files.join(", ")}
              </div>
            )}
          </>
        )}

        {leaderboard && (
          <>
            <div className="card" style={{ marginTop: "1.5rem" }}>
              <p className="section-label" style={{ margin: "0 0 0.75rem" }}>
                Pipeline progress
              </p>
              <FunnelChart stages={leaderboard.funnel} total={leaderboard.total_candidates} />
            </div>

            <p className="section-label">Candidates — click a row to open their profile</p>
            {leaderboard.candidates.length > 0 ? (
              <Leaderboard data={leaderboard} onRowClick={(c) => router.push(`/jobs/${jobId}/candidates/${c.id}`)} />
            ) : (
              <div className="empty-state">
                <p>No candidates yet — upload a tracker above to get started.</p>
              </div>
            )}
          </>
        )}

        <p className="section-label">Round management</p>
        {job && <RoundManagement jobId={jobId} jobTitle={job.title} onRoundsChanged={refresh} />}
      </main>
    </>
  );
}

export default function JobDetailPage() {
  return (
    <RequireAuth>
      <JobDetailInner />
    </RequireAuth>
  );
}
