"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import ConfirmDeleteModal from "@/components/ConfirmDeleteModal";
import { TrashIcon } from "@/components/icons";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { ApiError, archiveJob, deleteJob, listJobs, unarchiveJob } from "@/lib/api";
import type { Job } from "@/lib/types";

function JobsPageInner() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"active" | "archived">("active");
  const [confirmTarget, setConfirmTarget] = useState<Job | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const [modalError, setModalError] = useState("");

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

  const activeJobs = jobs?.filter((j) => j.status !== "archived") ?? [];
  const archivedJobs = jobs?.filter((j) => j.status === "archived") ?? [];
  const visibleJobs = tab === "active" ? activeJobs : archivedJobs;

  async function handleArchive(job: Job) {
    setModalBusy(true);
    setModalError("");
    try {
      const updated = await archiveJob(job.id);
      setJobs((prev) => prev?.map((j) => (j.id === job.id ? updated : j)) ?? null);
      setConfirmTarget(null);
    } catch (err) {
      setModalError(err instanceof Error ? err.message : "Couldn't archive this posting.");
    } finally {
      setModalBusy(false);
    }
  }

  async function handleDelete(job: Job) {
    setModalBusy(true);
    setModalError("");
    try {
      await deleteJob(job.id);
      setJobs((prev) => prev?.filter((j) => j.id !== job.id) ?? null);
      setConfirmTarget(null);
    } catch (err) {
      setModalError(err instanceof Error ? err.message : "Couldn't delete this posting.");
    } finally {
      setModalBusy(false);
    }
  }

  async function handleUnarchive(job: Job) {
    try {
      const updated = await unarchiveJob(job.id);
      setJobs((prev) => prev?.map((j) => (j.id === job.id ? updated : j)) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't unarchive this posting.");
    }
  }

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

        {jobs && jobs.length > 0 && (
          <div className="jobs-tabs">
            <button
              type="button"
              className={`jobs-tab${tab === "active" ? " jobs-tab-active" : ""}`}
              onClick={() => setTab("active")}
            >
              Active ({activeJobs.length})
            </button>
            <button
              type="button"
              className={`jobs-tab${tab === "archived" ? " jobs-tab-active" : ""}`}
              onClick={() => setTab("archived")}
            >
              Archived ({archivedJobs.length})
            </button>
          </div>
        )}

        {jobs && jobs.length === 0 && (
          <div className="empty-state">
            <p>No job postings yet.</p>
            <button className="btn btn-primary" onClick={() => router.push("/jobs/new")}>
              Create your first job posting
            </button>
          </div>
        )}

        {jobs && jobs.length > 0 && visibleJobs.length === 0 && (
          <div className="empty-state">
            <p>{tab === "active" ? "No active postings." : "No archived postings."}</p>
          </div>
        )}

        {visibleJobs.length > 0 && (
          <div className="job-grid">
            {visibleJobs.map((job) => (
              <div
                key={job.id}
                className={`card job-card${job.status === "archived" ? " job-card-archived" : ""}`}
                onClick={() => router.push(`/jobs/${job.id}`)}
              >
                <div className="job-card-top">
                  <span className={`badge badge-${job.status}`}>{job.status}</span>
                  <div className="job-card-top-actions">
                    <span className="job-card-date">{new Date(job.created_at).toLocaleDateString()}</span>
                    {job.status === "archived" && (
                      <button
                        type="button"
                        className="icon-delete-btn"
                        title="Unarchive"
                        aria-label={`Unarchive ${job.title}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleUnarchive(job);
                        }}
                      >
                        ↺
                      </button>
                    )}
                    <button
                      type="button"
                      className="icon-delete-btn"
                      title="Delete posting"
                      aria-label={`Delete ${job.title}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setModalError("");
                        setConfirmTarget(job);
                      }}
                    >
                      <TrashIcon />
                    </button>
                  </div>
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

      {confirmTarget && (
        <ConfirmDeleteModal
          title={`Delete "${confirmTarget.title}"?`}
          message="This will permanently delete all candidates, scores, rubrics, and screening/interview data for this posting. Please export any data you need before deleting — or archive this posting instead to keep it (read-only) without losing anything."
          onCancel={() => setConfirmTarget(null)}
          onArchive={confirmTarget.status === "archived" ? undefined : () => handleArchive(confirmTarget)}
          onDelete={() => handleDelete(confirmTarget)}
          busy={modalBusy}
          error={modalError}
        />
      )}
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
