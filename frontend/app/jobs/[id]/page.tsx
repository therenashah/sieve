"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import CandidateTable from "@/components/CandidateTable";
import FileUpload from "@/components/FileUpload";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { ApiError, getJob, getRubric, listCandidates, uploadCvs, uploadTracker } from "@/lib/api";
import type { Candidate, CvUploadResult, Job, Rubric, RowError } from "@/lib/types";

function JobDetailInner() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const router = useRouter();

  const [job, setJob] = useState<Job | null>(null);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [error, setError] = useState("");
  const [rowErrors, setRowErrors] = useState<RowError[]>([]);
  const [cvResult, setCvResult] = useState<CvUploadResult | null>(null);

  const refresh = useCallback(() => {
    Promise.all([getJob(jobId), listCandidates(jobId), getRubric(jobId)])
      .then(([j, c, r]) => {
        setJob(j);
        setCandidates(c);
        setRubric(r);
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

        {job && job.jd_filename && (
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <p className="section-label">
                {rubric ? `Scoring rubric (v${rubric.version})` : "Scoring rubric"}
              </p>
              <button className="link-back" onClick={refresh}>
                Refresh
              </button>
            </div>

            {!rubric && (
              <p className="page-subtitle">
                Generating the scoring rubric from the uploaded JD — this runs in the background and
                usually takes a few seconds. Click Refresh to check again.
              </p>
            )}

            {rubric && (
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.75rem" }}>
                {[...rubric.criteria]
                  .sort((a, b) => b.weight - a.weight)
                  .map((c) => (
                    <li key={c.id} style={{ borderBottom: "1px solid var(--border, #eee)", paddingBottom: "0.75rem" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
                        <strong>{c.name}</strong>
                        <span>{(c.weight * 100).toFixed(0)}%</span>
                      </div>
                      <p className="page-subtitle" style={{ margin: 0 }}>
                        {c.description}
                      </p>
                    </li>
                  ))}
              </ul>
            )}
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

        {candidates && candidates.length > 0 && (
          <>
            <p className="section-label">{candidates.length} candidates</p>
            <CandidateTable candidates={candidates} />
          </>
        )}

        {candidates && candidates.length === 0 && (
          <div className="empty-state">
            <p>No candidates yet — upload a tracker above to get started.</p>
          </div>
        )}
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
