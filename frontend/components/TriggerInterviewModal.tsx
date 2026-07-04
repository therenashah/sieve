"use client";

import { useState } from "react";

import { ApiError, triggerInterview } from "@/lib/api";
import type { TriggerInterviewResponse } from "@/lib/types";

export default function TriggerInterviewModal({
  jobId,
  candidateId,
  candidateName,
  roundKey,
  roundName,
  onClose,
  onCreated,
}: {
  jobId: number | string;
  candidateId: number | string;
  candidateName: string;
  roundKey: string;
  roundName: string;
  onClose: () => void;
  onCreated?: () => void;
}) {
  const [result, setResult] = useState<TriggerInterviewResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  async function handleCreate() {
    setSubmitting(true);
    setError("");
    try {
      const res = await triggerInterview(jobId, candidateId, roundKey);
      setResult(res);
      onCreated?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create an interview link — try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopy() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.interview_url);
      setCopied(true);
    } catch {
      // clipboard blocked — the link is still visible/selectable
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>
            {roundName} — {candidateName}
          </h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {!result && (
          <div className="modal-body">
            <p className="page-subtitle" style={{ margin: "0 0 1rem" }}>
              Generate a private interview link for {candidateName}. They&apos;ll open it, pick a slot within the
              next week, then join a live interview with the AI interviewer — camera on, voice-based. The scorecard
              and summary land on their candidate page once the interview ends. Nothing is sent anywhere; just copy
              the link.
            </p>
            {error && <div className="alert alert-error">{error}</div>}
            <div className="modal-footer" style={{ justifyContent: "flex-end" }}>
              <button className="btn btn-secondary" onClick={onClose}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleCreate} disabled={submitting}>
                {submitting ? "Creating…" : "Generate interview link"}
              </button>
            </div>
          </div>
        )}

        {result && (
          <div className="modal-body">
            <div className="screening-notification">
              <div className="screening-notification-title">Link ready — nothing was sent anywhere</div>
              <div className="screening-link-box">
                <input
                  className="screening-link-input"
                  type="text"
                  readOnly
                  value={result.interview_url}
                  onFocus={(e) => e.currentTarget.select()}
                />
                <button className="btn btn-small btn-secondary" onClick={handleCopy}>
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <div className="screening-action-meta">
                <a href={result.interview_url} target="_blank" rel="noreferrer">
                  Open in new tab
                </a>
                <span>· schedule &amp; join by {new Date(result.expires_at).toLocaleDateString()}</span>
              </div>
            </div>
            <div className="modal-footer" style={{ justifyContent: "flex-end" }}>
              <button className="btn btn-primary" onClick={onClose}>
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
