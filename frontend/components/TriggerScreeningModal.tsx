"use client";

import { useEffect, useState } from "react";

import { addQuestion, ApiError, deleteQuestion, generateQuestions, listQuestions, triggerScreening } from "@/lib/api";
import type { JobQuestion, TriggerScreeningResponse } from "@/lib/types";

const SOURCE_LABEL: Record<string, string> = {
  default: "Standard",
  ai: "AI recommended",
  custom: "Added by you",
};

export default function TriggerScreeningModal({
  jobId,
  candidateId,
  candidateName,
  onClose,
}: {
  jobId: number | string;
  candidateId: number | string;
  candidateName: string;
  onClose: () => void;
}) {
  const [questions, setQuestions] = useState<JobQuestion[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [newQuestion, setNewQuestion] = useState("");
  const [adding, setAdding] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [result, setResult] = useState<TriggerScreeningResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState("");

  useEffect(() => {
    listQuestions(jobId)
      .then((qs) => {
        setQuestions(qs);
        setSelected(new Set(qs.map((q) => q.id)));
      })
      .catch(() => setLoadError("Couldn't load screening questions for this job."));
  }, [jobId]);

  async function handleGenerateFromJD() {
    setGenerating(true);
    setGenerateError("");
    try {
      const qs = await generateQuestions(jobId);
      setQuestions(qs);
      setSelected((prev) => {
        const next = new Set(prev);
        qs.forEach((q) => next.add(q.id));
        return next;
      });
    } catch (err) {
      setGenerateError(
        err instanceof ApiError ? err.message : "Couldn't generate questions — try again."
      );
    } finally {
      setGenerating(false);
    }
  }

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleAddQuestion() {
    const text = newQuestion.trim();
    if (!text) return;
    setAdding(true);
    try {
      const created = await addQuestion(jobId, text);
      setQuestions((prev) => [...(prev ?? []), created]);
      setSelected((prev) => new Set(prev).add(created.id));
      setNewQuestion("");
    } catch {
      setLoadError("Couldn't add that question — try again.");
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(id: number) {
    setQuestions((prev) => (prev ?? []).filter((q) => q.id !== id));
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    try {
      await deleteQuestion(jobId, id);
    } catch {
      // Non-critical — it's already removed from this session's selection either way.
    }
  }

  async function handleConfirm() {
    setSubmitting(true);
    setSubmitError("");
    try {
      const res = await triggerScreening(jobId, candidateId, Array.from(selected));
      setResult(res);
    } catch (err) {
      setSubmitError(
        err instanceof ApiError ? err.message : "Couldn't create a screening link — is the API running?"
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopy() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.chat_url);
      setCopied(true);
    } catch {
      // Clipboard permission denied — link is still visible/selectable.
    }
  }

  const grouped = questions
    ? (["default", "ai", "custom"] as const).map((source) => ({
        source,
        items: questions.filter((q) => q.source === source),
      }))
    : [];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>HR Screening — {candidateName}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {!result && (
          <>
            <p className="page-subtitle" style={{ margin: "0 0 1rem" }}>
              Pick the questions this candidate should be asked, in order. The chat asks all of these
              first, then follows up on anything worth clarifying in their profile.
            </p>

            <div className="modal-body">
              {loadError && <div className="alert alert-error">{loadError}</div>}
              {!questions && !loadError && <p className="page-subtitle">Loading questions…</p>}

              {questions && grouped.every((g) => g.source !== "ai" || g.items.length === 0) && (
                <div className="alert alert-warning" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem" }}>
                  <span>No AI-recommended questions yet for this job&apos;s JD.</span>
                  <button
                    type="button"
                    className="btn btn-small btn-secondary"
                    onClick={handleGenerateFromJD}
                    disabled={generating}
                  >
                    {generating ? "Generating…" : "Generate from JD"}
                  </button>
                </div>
              )}
              {generateError && <div className="alert alert-error">{generateError}</div>}

              {grouped.map(
                (group) =>
                  group.items.length > 0 && (
                    <div key={group.source} className="question-group">
                      <p className="section-label" style={{ margin: "0.75rem 0 0.4rem" }}>
                        {SOURCE_LABEL[group.source]}
                      </p>
                      {group.items.map((q) => (
                        <label key={q.id} className="question-row">
                          <input
                            type="checkbox"
                            checked={selected.has(q.id)}
                            onChange={() => toggle(q.id)}
                          />
                          <span className="question-text">{q.question_text}</span>
                          {q.source === "ai" && <span className="badge badge-neutral">AI</span>}
                          <button
                            type="button"
                            className="question-remove"
                            onClick={() => handleRemove(q.id)}
                            aria-label="Remove question"
                          >
                            ×
                          </button>
                        </label>
                      ))}
                    </div>
                  )
              )}

              <div className="question-add-row">
                <input
                  type="text"
                  value={newQuestion}
                  onChange={(e) => setNewQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddQuestion()}
                  placeholder="Add a custom question…"
                />
                <button
                  type="button"
                  className="btn btn-small btn-secondary"
                  onClick={handleAddQuestion}
                  disabled={adding || !newQuestion.trim()}
                >
                  Add
                </button>
              </div>
            </div>

            {submitError && <div className="alert alert-error">{submitError}</div>}

            <div className="modal-footer">
              <span className="page-subtitle" style={{ margin: 0 }}>
                {selected.size} question{selected.size === 1 ? "" : "s"} selected
              </span>
              <div style={{ display: "flex", gap: "0.6rem" }}>
                <button className="btn btn-secondary" onClick={onClose}>
                  Cancel
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleConfirm}
                  disabled={submitting || !questions}
                >
                  {submitting ? "Creating…" : "Confirm & trigger"}
                </button>
              </div>
            </div>
          </>
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
                  value={result.chat_url}
                  onFocus={(e) => e.currentTarget.select()}
                />
                <button className="btn btn-small btn-secondary" onClick={handleCopy}>
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <div className="screening-action-meta">
                <a href={result.chat_url} target="_blank" rel="noreferrer">
                  Open in new tab
                </a>
                <span>· expires {new Date(result.expires_at).toLocaleString()}</span>
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
