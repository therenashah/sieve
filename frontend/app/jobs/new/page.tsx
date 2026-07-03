"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import CandidateTable from "@/components/CandidateTable";
import FileUpload from "@/components/FileUpload";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { createJob, uploadCvs, uploadJD, uploadTracker } from "@/lib/api";
import type { Candidate, CvUploadResult, RowError } from "@/lib/types";

function NewJobPageInner() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [jobId, setJobId] = useState<number | null>(null);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [jdFile, setJdFile] = useState<File | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [rowErrors, setRowErrors] = useState<RowError[]>([]);
  const [cvResult, setCvResult] = useState<CvUploadResult | null>(null);

  async function handleCreateJob(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setCreateError("Give the role a title first.");
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      const job = await createJob(title.trim(), description.trim());
      if (jdFile) {
        await uploadJD(job.id, jdFile);
      }
      setJobId(job.id);
      setStep(2);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Couldn't create the job posting.");
    } finally {
      setCreating(false);
    }
  }

  async function handleTrackerUpload(file: File) {
    if (!jobId) return;
    const result = await uploadTracker(jobId, file);
    setCandidates(result.candidates);
    setRowErrors(result.row_errors);
  }

  async function handleCvUpload(file: File) {
    if (!jobId) return;
    const result = await uploadCvs(jobId, file);
    setCvResult(result);
  }

  return (
    <>
      <Navbar />
      <main className="page page-narrow">
        <button className="link-back" onClick={() => router.push("/jobs")}>
          ← All postings
        </button>

        <div className="page-header">
          <div>
            <h1>New job posting</h1>
            <p className="page-subtitle">
              Create the requisition, then bring in your candidate tracker and CVs.
            </p>
          </div>
        </div>

        <div className="stepper">
          <div className={`step ${step >= 1 ? "step-active" : ""}`}>1. Job details</div>
          <div className={`step ${step >= 2 ? "step-active" : ""}`}>2. Candidate tracker</div>
          <div className={`step ${step >= 3 ? "step-active" : ""}`}>3. Candidate CVs</div>
        </div>

        {step === 1 && (
          <form className="card form-card" onSubmit={handleCreateJob}>
            <label className="field">
              <span>Job title</span>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Backend Engineer — Platform Team"
                required
              />
            </label>
            <label className="field">
              <span>Description (optional)</span>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
                placeholder="Short internal note about this role"
              />
            </label>
            <label className="field">
              <span>Job description document (optional — PDF or Word)</span>
              <input
                type="file"
                accept=".pdf,.doc,.docx"
                onChange={(e) => setJdFile(e.target.files?.[0] ?? null)}
              />
            </label>
            {createError && <div className="alert alert-error">{createError}</div>}
            <button className="btn btn-primary" type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create job & continue"}
            </button>
          </form>
        )}

        {step === 2 && jobId && (
          <div className="card">
            <FileUpload
              accept=".csv,.xlsx,.xls"
              label="Upload candidate tracker"
              hint="CSV or Excel export with Candidate Name, Candidate ID, Match Score, etc."
              onUpload={handleTrackerUpload}
            />

            {rowErrors.length > 0 && (
              <div className="alert alert-warning">
                <strong>{rowErrors.length} row(s) couldn&apos;t be imported:</strong>
                <ul>
                  {rowErrors.slice(0, 8).map((e, i) => (
                    <li key={i}>
                      Row {e.row}: {e.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {candidates.length > 0 && (
              <>
                <p className="section-label">{candidates.length} candidates imported</p>
                <CandidateTable candidates={candidates} />
                <div className="wizard-actions">
                  <button className="btn btn-primary" onClick={() => setStep(3)}>
                    Continue to CV upload
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {step === 3 && jobId && (
          <div className="card">
            <FileUpload
              accept=".zip"
              label="Upload candidate CVs (.zip)"
              hint="File names should roughly match candidate names — we'll match them automatically."
              onUpload={handleCvUpload}
            />

            {cvResult && (
              <div className="cv-results">
                <div className="alert alert-success">
                  Matched {cvResult.matched.length} of {cvResult.total_candidates} candidates to a CV.
                </div>

                {cvResult.unmatched_candidates.length > 0 && (
                  <div className="alert alert-warning">
                    <strong>{cvResult.unmatched_candidates.length} candidate(s) have no matching CV:</strong>
                    <ul>
                      {cvResult.unmatched_candidates.map((c) => (
                        <li key={c.id}>
                          {c.name} ({c.external_id})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {cvResult.unmatched_files.length > 0 && (
                  <div className="alert alert-warning">
                    <strong>
                      {cvResult.unmatched_files.length} file(s) in the zip couldn&apos;t be matched and were
                      dropped:
                    </strong>
                    <ul>
                      {cvResult.unmatched_files.map((f, i) => (
                        <li key={i}>{f}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {cvResult.skipped_non_resume_files.length > 0 && (
                  <div className="alert alert-warning">
                    <strong>{cvResult.skipped_non_resume_files.length} non-resume file(s) ignored:</strong>{" "}
                    {cvResult.skipped_non_resume_files.join(", ")}
                  </div>
                )}

                <div className="wizard-actions">
                  <button className="btn btn-primary" onClick={() => router.push(`/jobs/${jobId}`)}>
                    Finish → view job
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </>
  );
}

export default function NewJobPage() {
  return (
    <RequireAuth>
      <NewJobPageInner />
    </RequireAuth>
  );
}
