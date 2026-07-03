"use client";

import { useState } from "react";

import { addRound, ApiError, updateRound } from "@/lib/api";
import type { JobRound, RoundAIConfig, RoundDifficulty, RoundTemplate } from "@/lib/types";

function defaultAIConfig(roundName: string, jobTitle: string): RoundAIConfig {
  return {
    share_jd: true,
    share_profile: true,
    share_resume: true,
    share_previous_rounds: true,
    share_rubric: true,
    instructions:
      `Conduct the ${roundName || "interview"} for the ${jobTitle} role. Ask clear, structured questions ` +
      "based on the job description and the candidate's profile, probe for depth on vague or evasive " +
      "answers, and stay professional and unbiased throughout.",
    duration_minutes: 30,
    difficulty: "balanced",
    focus_areas: "",
    allow_candidate_questions: true,
    store_transcript: true,
    store_recording: false,
    generate_scorecard: true,
    flag_inconsistencies: true,
  };
}

// Older rounds may have been saved before these fields existed — backfill defaults.
function withDefaults(config: RoundAIConfig): RoundAIConfig {
  return {
    ...defaultAIConfig("", ""),
    ...config,
  };
}

export default function RoundEditModal({
  jobId,
  jobTitle,
  template,
  existingRound,
  onClose,
  onSaved,
}: {
  jobId: number | string;
  jobTitle: string;
  template?: RoundTemplate;
  existingRound?: JobRound;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!existingRound;
  const [name, setName] = useState(existingRound?.name ?? template?.name ?? "");
  const [description, setDescription] = useState(existingRound?.description ?? template?.description ?? "");
  const [isAiBased, setIsAiBased] = useState(existingRound?.is_ai_based ?? false);
  const [aiConfig, setAiConfig] = useState<RoundAIConfig>(
    existingRound?.ai_config
      ? withDefaults(existingRound.ai_config)
      : defaultAIConfig(existingRound?.name ?? template?.name ?? "", jobTitle)
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function updateField<K extends keyof RoundAIConfig>(key: K, value: RoundAIConfig[K]) {
    setAiConfig((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Round name is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (isEdit) {
        await updateRound(jobId, existingRound.id, {
          name: trimmedName,
          description,
          is_ai_based: isAiBased,
          ai_config: isAiBased ? aiConfig : null,
        });
      } else if (template) {
        const created = await addRound(jobId, template.key, trimmedName, description);
        if (isAiBased) {
          await updateRound(jobId, created.id, {
            name: trimmedName,
            description,
            is_ai_based: true,
            ai_config: aiConfig,
          });
        }
      }
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save this round — try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{isEdit ? `Edit ${existingRound.name}` : `Add ${template?.name ?? "round"}`}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal-body">
          <label className="field">
            <span>Round name</span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field" style={{ marginTop: "0.9rem" }}>
            <span>Description</span>
            <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>

          <label className="round-ai-toggle">
            <input type="checkbox" checked={isAiBased} onChange={(e) => setIsAiBased(e.target.checked)} />
            <span>AI-based round (an AI interviewer conducts this round)</span>
          </label>

          {isAiBased && (
            <div className="round-ai-config">
              <p className="section-label" style={{ margin: "0.5rem 0 0.4rem" }}>
                Share with the AI interviewer
              </p>
              <div className="round-ai-grid">
                {(
                  [
                    ["share_jd", "Job description"],
                    ["share_profile", "Candidate master profile"],
                    ["share_resume", "Candidate resume / CV"],
                    ["share_previous_rounds", "Previous round scores & summaries"],
                    ["share_rubric", "Screening rubric / scoring criteria"],
                  ] as [keyof RoundAIConfig, string][]
                ).map(([key, label]) => (
                  <label key={key} className="round-ai-checkbox">
                    <input
                      type="checkbox"
                      checked={aiConfig[key] as boolean}
                      onChange={(e) => updateField(key, e.target.checked as never)}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>

              <label className="field" style={{ marginTop: "0.9rem" }}>
                <span>Instructions for the AI interviewer</span>
                <textarea
                  rows={3}
                  value={aiConfig.instructions}
                  onChange={(e) => updateField("instructions", e.target.value)}
                />
              </label>

              <p className="section-label" style={{ margin: "0.9rem 0 0.4rem" }}>
                Interview format
              </p>
              <div className="round-ai-grid">
                <label className="field">
                  <span>Approx. duration (minutes)</span>
                  <input
                    type="number"
                    min={5}
                    max={90}
                    step={5}
                    value={aiConfig.duration_minutes}
                    onChange={(e) =>
                      updateField("duration_minutes", Math.max(5, Math.min(90, Number(e.target.value) || 30)))
                    }
                  />
                </label>
                <label className="field">
                  <span>Difficulty</span>
                  <select
                    className="text-input"
                    value={aiConfig.difficulty}
                    onChange={(e) => updateField("difficulty", e.target.value as RoundDifficulty)}
                  >
                    <option value="easy">Easy</option>
                    <option value="balanced">Balanced</option>
                    <option value="hard">Hard</option>
                  </select>
                </label>
              </div>
              <label className="field" style={{ marginTop: "0.9rem" }}>
                <span>Focus areas (optional)</span>
                <input
                  type="text"
                  value={aiConfig.focus_areas}
                  placeholder="e.g. system design, ownership, incident response"
                  onChange={(e) => updateField("focus_areas", e.target.value)}
                />
              </label>
              <label className="round-ai-checkbox" style={{ marginTop: "0.6rem" }}>
                <input
                  type="checkbox"
                  checked={aiConfig.allow_candidate_questions}
                  onChange={(e) => updateField("allow_candidate_questions", e.target.checked as never)}
                />
                <span>Let the candidate ask questions before wrapping up</span>
              </label>

              <p className="section-label" style={{ margin: "0.9rem 0 0.4rem" }}>
                Outcome & evaluation
              </p>
              <div className="round-ai-grid">
                {(
                  [
                    ["store_transcript", "Store interview transcript"],
                    ["store_recording", "Store audio/video recording"],
                    ["generate_scorecard", "Generate AI scorecard & summary"],
                    ["flag_inconsistencies", "Flag inconsistencies (red/green flags)"],
                  ] as [keyof RoundAIConfig, string][]
                ).map(([key, label]) => (
                  <label key={key} className="round-ai-checkbox">
                    <input
                      type="checkbox"
                      checked={aiConfig[key] as boolean}
                      onChange={(e) => updateField(key, e.target.checked as never)}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {error && <div className="alert alert-error">{error}</div>}
        </div>

        <div className="modal-footer" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save round" : "Add round"}
          </button>
        </div>
      </div>
    </div>
  );
}
