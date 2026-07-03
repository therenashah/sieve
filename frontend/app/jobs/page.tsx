"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { ApiError, listJobs } from "@/lib/api";
import type { Job } from "@/lib/types";

function JobsPageInner() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listJobs()
      .then(setJobs)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/");
          return;
        }
        setError("Couldn't load job postings. Is the API running?");
      });
  }, [router]);

  return (
    <>
      <Navbar />
      <main className="page">
        <div className="page-header">
          <div>
            <h1>Job postings</h1>
            <p className="page-subtitle">Every requisition you&apos;re screening candidates for.</p>
          </div>
          <button className="btn btn-primary" onClick={() => router.push("/jobs/new")}>
            + New job posting
          </button>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        {jobs === null && !error && <div className="empty-state">Loading postings…</div>}

        {jobs && jobs.length === 0 && (
          <div className="empty-state">
            <p>No job postings yet.</p>
            <button className="btn btn-primary" onClick={() => router.push("/jobs/new")}>
              Create your first job posting
            </button>
          </div>
        )}

        {jobs && jobs.length > 0 && (
          <div className="job-grid">
            {jobs.map((job) => (
              <div key={job.id} className="card job-card" onClick={() => router.push(`/jobs/${job.id}`)}>
                <div className="job-card-top">
                  <span className={`badge badge-${job.status}`}>{job.status}</span>
                  <span className="job-card-date">{new Date(job.created_at).toLocaleDateString()}</span>
                </div>
                <h3 className="job-card-title">{job.title}</h3>
                <p className="job-card-desc">{job.description || "No description provided."}</p>
                <div className="job-card-stats">
                  <span>{job.candidate_count ?? 0} candidates</span>
                  <span>·</span>
                  <span>{job.cvs_matched ?? 0} CVs on file</span>
                  <span>·</span>
                  <span>{job.jd_filename ? "JD uploaded" : "No JD"}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </>
  );
}

export default function JobsPage() {
  return (
    <RequireAuth>
      <JobsPageInner />
    </RequireAuth>
  );
}
