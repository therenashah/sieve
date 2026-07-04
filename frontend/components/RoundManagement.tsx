"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import ConfirmDeleteModal from "@/components/ConfirmDeleteModal";
import { TrashIcon } from "@/components/icons";
import RoundEditModal from "@/components/RoundEditModal";
import { deleteRound, listRounds, listRoundTemplates } from "@/lib/api";
import type { JobRound, RoundTemplate } from "@/lib/types";

const BUILTIN_LINKS: Record<string, string> = {
  resume_screening: "screening",
  hr_screening: "rounds/hr-screening",
};

const BUILTIN_SUBTITLES: Record<string, string> = {
  resume_screening: "Rubric, AI scan, ranked candidates",
  hr_screening: "Trigger chats, review summaries",
};

export default function RoundManagement({
  jobId,
  jobTitle,
  onRoundsChanged,
  readOnly = false,
}: {
  jobId: string;
  jobTitle: string;
  onRoundsChanged?: () => void;
  readOnly?: boolean;
}) {
  const router = useRouter();
  const [rounds, setRounds] = useState<JobRound[] | null>(null);
  const [templates, setTemplates] = useState<RoundTemplate[]>([]);
  const [editingRound, setEditingRound] = useState<JobRound | null>(null);
  const [addingTemplate, setAddingTemplate] = useState<RoundTemplate | null>(null);
  const [deletingRound, setDeletingRound] = useState<JobRound | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  const refresh = useCallback(() => {
    Promise.all([listRounds(jobId), listRoundTemplates(jobId)]).then(([r, t]) => {
      setRounds(r);
      setTemplates(t);
    });
  }, [jobId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function handleSaved() {
    setEditingRound(null);
    setAddingTemplate(null);
    refresh();
    onRoundsChanged?.();
  }

  async function handleDeleteRound() {
    if (!deletingRound) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await deleteRound(jobId, deletingRound.id);
      setDeletingRound(null);
      refresh();
      onRoundsChanged?.();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Couldn't delete this round.");
    } finally {
      setDeleteBusy(false);
    }
  }

  const builtinRounds = rounds?.filter((r) => r.is_builtin) ?? [];
  const optionalRounds = rounds?.filter((r) => !r.is_builtin) ?? [];

  return (
    <>
      <div className="round-grid">
        {builtinRounds.map((r, i) => (
          <div
            key={r.round_key}
            className="card round-card"
            onClick={() => router.push(`/jobs/${jobId}/${BUILTIN_LINKS[r.round_key] ?? ""}`)}
          >
            <span className="round-card-number">{i + 1}</span>
            <div>
              <div className="round-card-title">{r.name}</div>
              <div className="round-card-subtitle">{BUILTIN_SUBTITLES[r.round_key] ?? r.description}</div>
            </div>
          </div>
        ))}

        {optionalRounds.map((r, i) => (
          <div
            key={r.round_key}
            className={`card round-card round-card-optional${r.is_ai_based ? "" : " round-card-static"}`}
            onClick={r.is_ai_based ? () => router.push(`/jobs/${jobId}/rounds/${r.round_key}`) : undefined}
            style={r.is_ai_based ? { cursor: "pointer" } : undefined}
          >
            <span className="round-card-number">{builtinRounds.length + i + 1}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="round-card-title">{r.name}</div>
              <div className="round-card-subtitle">
                {r.is_ai_based ? "AI interview · trigger & review" : "Manual round"}
              </div>
            </div>
            {!readOnly && (
              <div className="round-card-icons">
                <button
                  type="button"
                  className="round-edit-icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditingRound(r);
                  }}
                  aria-label={`Edit ${r.name}`}
                >
                  ✎
                </button>
                <button
                  type="button"
                  className="round-delete-icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteError("");
                    setDeletingRound(r);
                  }}
                  aria-label={`Delete ${r.name}`}
                >
                  <TrashIcon />
                </button>
              </div>
            )}
          </div>
        ))}

        {!readOnly &&
          templates.map((t) => (
            <button key={t.key} type="button" className="round-add-box" onClick={() => setAddingTemplate(t)}>
              <span className="round-add-icon">+</span>
              <span>{t.name}</span>
            </button>
          ))}
      </div>

      {editingRound && (
        <RoundEditModal
          jobId={jobId}
          jobTitle={jobTitle}
          existingRound={editingRound}
          onClose={() => setEditingRound(null)}
          onSaved={handleSaved}
        />
      )}

      {addingTemplate && (
        <RoundEditModal
          jobId={jobId}
          jobTitle={jobTitle}
          template={addingTemplate}
          onClose={() => setAddingTemplate(null)}
          onSaved={handleSaved}
        />
      )}

      {deletingRound && (
        <ConfirmDeleteModal
          title={`Delete "${deletingRound.name}"?`}
          message={`This deletes all data recorded for this round${
            deletingRound.is_ai_based ? " — interview sessions, transcripts, recordings, and scores" : " and scores"
          } for every candidate. It can't be undone, though you can add ${deletingRound.name} back later as a fresh round.`}
          onCancel={() => setDeletingRound(null)}
          onDelete={handleDeleteRound}
          busy={deleteBusy}
          error={deleteError}
        />
      )}
    </>
  );
}
