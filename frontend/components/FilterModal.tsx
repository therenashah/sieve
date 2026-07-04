"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError, getFilterFacets, listCandidates, parseFilters } from "@/lib/api";
import type { Candidate, Filter, FilterFacets, FilterSet } from "@/lib/types";

// Debounce live-preview calls so every checkbox click / keystroke doesn't fire its own
// request -- only the settled selection does.
const PREVIEW_DEBOUNCE_MS = 350;

function buildManualFilters(
  locations: Set<string>,
  skills: Set<string>,
  buckets: Set<string>,
): Filter[] {
  const filters: Filter[] = [];
  if (locations.size > 0) {
    filters.push({ field: "location", op: "in", value: Array.from(locations), criterion_id: null });
  }
  if (skills.size > 0) {
    filters.push({ field: "skills", op: "in", value: Array.from(skills), criterion_id: null });
  }
  if (buckets.size > 0) {
    filters.push({ field: "experience_bucket", op: "in", value: Array.from(buckets), criterion_id: null });
  }
  return filters;
}

export default function FilterModal({
  jobId,
  initialFilterSet,
  onApply,
  onClose,
}: {
  jobId: number | string;
  initialFilterSet: FilterSet | null;
  onApply: (fs: FilterSet | null) => void;
  onClose: () => void;
}) {
  const [facets, setFacets] = useState<FilterFacets | null>(null);
  const [facetsError, setFacetsError] = useState("");

  const initialManual = initialFilterSet?.filters.filter((f) => f.op === "in") ?? [];
  const initialPromptFilters = initialFilterSet?.filters.filter((f) => f.op !== "in") ?? [];

  const [selectedLocations, setSelectedLocations] = useState<Set<string>>(
    new Set((initialManual.find((f) => f.field === "location")?.value as string[]) ?? []),
  );
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(
    new Set((initialManual.find((f) => f.field === "skills")?.value as string[]) ?? []),
  );
  const [selectedBuckets, setSelectedBuckets] = useState<Set<string>>(
    new Set((initialManual.find((f) => f.field === "experience_bucket")?.value as string[]) ?? []),
  );

  const [promptText, setPromptText] = useState("");
  const [promptFilters, setPromptFilters] = useState<Filter[]>(initialPromptFilters);
  const [promptUnparsed, setPromptUnparsed] = useState<string[]>(initialFilterSet?.unparsed ?? []);
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptError, setPromptError] = useState("");

  const [previewCandidates, setPreviewCandidates] = useState<Candidate[] | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");

  useEffect(() => {
    getFilterFacets(jobId)
      .then(setFacets)
      .catch(() => setFacetsError("Couldn't load filter options for this job."));
  }, [jobId]);

  const combinedFilterSet: FilterSet = useMemo(
    () => ({
      filters: [...buildManualFilters(selectedLocations, selectedSkills, selectedBuckets), ...promptFilters],
      unparsed: promptUnparsed,
    }),
    [selectedLocations, selectedSkills, selectedBuckets, promptFilters, promptUnparsed],
  );

  const hasAnyFilter = combinedFilterSet.filters.length > 0;

  useEffect(() => {
    if (!hasAnyFilter) {
      setPreviewCandidates(null);
      setPreviewError("");
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    const timer = setTimeout(() => {
      listCandidates(jobId, { filter: JSON.stringify(combinedFilterSet) })
        .then((res) => {
          if (cancelled) return;
          setPreviewCandidates(res.candidates);
          setPreviewError("");
        })
        .catch((err) => {
          if (cancelled) return;
          setPreviewError(err instanceof ApiError ? err.message : "Couldn't preview matches for this filter.");
        })
        .finally(() => {
          if (!cancelled) setPreviewLoading(false);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, hasAnyFilter, JSON.stringify(combinedFilterSet)]);

  function toggleInSet(set: Set<string>, setter: (s: Set<string>) => void, value: string) {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setter(next);
  }

  async function runPrompt() {
    if (!promptText.trim()) return;
    setPromptLoading(true);
    setPromptError("");
    try {
      const fs = await parseFilters(jobId, promptText.trim());
      setPromptFilters(fs.filters);
      setPromptUnparsed(fs.unparsed);
    } catch (err) {
      setPromptError(err instanceof ApiError ? err.message : "Couldn't understand that filter — try rephrasing.");
    } finally {
      setPromptLoading(false);
    }
  }

  function clearAll() {
    setSelectedLocations(new Set());
    setSelectedSkills(new Set());
    setSelectedBuckets(new Set());
    setPromptText("");
    setPromptFilters([]);
    setPromptUnparsed([]);
    setPromptError("");
  }

  function handleApply() {
    onApply(hasAnyFilter ? combinedFilterSet : null);
    onClose();
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Filter candidates</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {facetsError && <div className="alert alert-error">{facetsError}</div>}

        <div className="modal-body filter-modal-grid">
          <div className="filter-panel-left">
            {!facets && !facetsError && <p className="page-subtitle">Loading filter options…</p>}

            {facets && (
              <>
                {facets.locations.length > 0 && (
                  <div className="filter-facet-group">
                    <p className="filter-facet-title">Location</p>
                    {facets.locations.map((loc) => (
                      <label key={loc} className="question-row">
                        <input
                          type="checkbox"
                          checked={selectedLocations.has(loc)}
                          onChange={() => toggleInSet(selectedLocations, setSelectedLocations, loc)}
                        />
                        <span className="question-text">{loc}</span>
                      </label>
                    ))}
                  </div>
                )}

                {facets.experience_buckets.length > 0 && (
                  <div className="filter-facet-group">
                    <p className="filter-facet-title">Years of experience</p>
                    {facets.experience_buckets.map((b) => (
                      <label key={b.key} className="question-row">
                        <input
                          type="checkbox"
                          checked={selectedBuckets.has(b.key)}
                          onChange={() => toggleInSet(selectedBuckets, setSelectedBuckets, b.key)}
                        />
                        <span className="question-text">{b.label}</span>
                      </label>
                    ))}
                  </div>
                )}

                {facets.skills.length > 0 && (
                  <div className="filter-facet-group">
                    <p className="filter-facet-title">Skills</p>
                    {facets.skills.map((skill) => (
                      <label key={skill} className="question-row">
                        <input
                          type="checkbox"
                          checked={selectedSkills.has(skill)}
                          onChange={() => toggleInSet(selectedSkills, setSelectedSkills, skill)}
                        />
                        <span className="question-text">{skill}</span>
                      </label>
                    ))}
                  </div>
                )}
              </>
            )}

            <div className="filter-facet-group">
              <p className="filter-facet-title">Ask in your own words</p>
              <textarea
                className="filter-prompt-input"
                rows={3}
                value={promptText}
                onChange={(e) => setPromptText(e.target.value)}
                placeholder='e.g. "engineer with 6+ yoe" or "strong kubernetes background based in Mumbai"'
              />
              <button className="btn btn-secondary btn-sm" onClick={runPrompt} disabled={promptLoading || !promptText.trim()}>
                {promptLoading ? "Matching…" : "Match with AI"}
              </button>
              {promptError && <div className="alert alert-error" style={{ marginTop: "0.5rem" }}>{promptError}</div>}
              {promptFilters.length > 0 && (
                <div className="filter-chip-row">
                  {promptFilters.map((f, i) => (
                    <span key={i} className="badge badge-neutral">
                      {f.field} {f.op} {f.criterion_id ? `(${f.criterion_id}) ` : ""}
                      {Array.isArray(f.value) ? f.value.join(", ") : String(f.value)}
                    </span>
                  ))}
                </div>
              )}
              {promptUnparsed.length > 0 && (
                <div className="alert alert-warning" style={{ marginTop: "0.5rem" }}>
                  Couldn&apos;t confidently map: {promptUnparsed.join(", ")}
                </div>
              )}
            </div>
          </div>

          <div className="filter-panel-right">
            <p className="filter-facet-title">
              {!hasAnyFilter
                ? "All candidates (no filters applied yet)"
                : previewLoading
                  ? "Matching…"
                  : `${previewCandidates?.length ?? 0} matching candidate${previewCandidates?.length === 1 ? "" : "s"}`}
            </p>
            {previewError && <div className="alert alert-error">{previewError}</div>}
            <div className="filter-preview-list">
              {hasAnyFilter && !previewLoading && previewCandidates?.length === 0 && (
                <p className="page-subtitle">No candidates match these criteria yet.</p>
              )}
              {(hasAnyFilter ? previewCandidates : null)?.map((c) => (
                <div key={c.id} className="filter-preview-row">
                  <span className="cand-name">{c.name}</span>
                  {c.overall != null && <span className="score-pill score-mid">{Math.round(c.overall * 100)}</span>}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={clearAll}>
            Clear all
          </button>
          <div style={{ display: "flex", gap: "0.6rem" }}>
            <button className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={handleApply}>
              Apply filters
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
