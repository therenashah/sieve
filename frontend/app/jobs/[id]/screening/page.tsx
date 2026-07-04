"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import TriggerScreeningModal from "@/components/TriggerScreeningModal";
import {
  ApiError,
  applyRubric,
  getJob,
  getRubric,
  listCandidates,
  parseFilters,
  rejectCandidate,
  rubricChat,
  scanCandidates,
  unrejectCandidate,
} from "@/lib/api";
import type { Candidate, Criterion, FilterSet, Job, Rubric, RubricDiff } from "@/lib/types";

// Highlighting is relative to the current (filtered) list, not a fixed score cutoff --
// the goal is surfacing "the top handful worth HR's attention", not a pass/fail bar.
const GREEN_FRACTION = 0.15;
const RED_FRACTION = 0.3;

function scoreClassForRank(index: number, total: number): string {
  if (total === 0) return "score-mid";
  const greenCount = Math.max(1, Math.ceil(total * GREEN_FRACTION));
  const redCount = Math.max(1, Math.ceil(total * RED_FRACTION));
  if (index < greenCount) return "score-high";
  if (index >= total - redCount) return "score-low";
  return "score-mid";
}

// Same status vocabulary/coloring as the job page's Leaderboard (components/Leaderboard.tsx)
// -- duplicated locally rather than imported since it's a tiny pure function and this
// avoids coupling two independent pages' bundles to one shared module for 5 lines.
function statusBadgeClass(status: string): string {
  if (status.includes("pending")) return "badge-warning";
  if (status === "All rounds completed") return "badge-success";
  return "badge-neutral";
}

// Rubric descriptions follow the "3: ... 6: ... 9: ..." anchor convention from the
// rubric-generation prompt. Parse it into labeled tiers HR can skim, falling back to the
// raw text for anything written differently (e.g. manually edited off-format).
const ANCHOR_LABELS: Record<string, string> = { "3": "Basic", "6": "Proficient", "9": "Expert" };

function parseAnchors(description: string): { level: string; label: string; text: string }[] | null {
  const matches = [...description.matchAll(/(\d+)\s*:\s*([^]*?)(?=(?:\d+\s*:)|$)/g)];
  if (matches.length < 2) return null;
  return matches.map(([, level, text]) => ({
    level,
    label: ANCHOR_LABELS[level] ?? `Level ${level}`,
    text: text.trim().replace(/\.$/, ""),
  }));
}

type SortKey = "name" | "overall" | "status" | "flags" | "decision" | null;
type SortDir = "asc" | "desc";

function ScreeningPageInner() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const router = useRouter();

  const [job, setJob] = useState<Job | null>(null);
  const [rubric, setRubricState] = useState<Rubric | null>(null);
  const [editedCriteria, setEditedCriteria] = useState<Criterion[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [error, setError] = useState("");
  const [savingRubric, setSavingRubric] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [screeningCandidate, setScreeningCandidate] = useState<Candidate | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatReply, setChatReply] = useState<string | null>(null);
  const [chatDiff, setChatDiff] = useState<RubricDiff | null>(null);
  const [proposedRubric, setProposedRubric] = useState<Rubric | null>(null);
  const [chatLoading, setChatLoading] = useState(false);

  const [filterInput, setFilterInput] = useState("");
  const [activeFilterSet, setActiveFilterSet] = useState<FilterSet | null>(null);
  const [unparsedFragments, setUnparsedFragments] = useState<string[]>([]);
  const [filterLoading, setFilterLoading] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeFilterRef = useRef<FilterSet | null>(null);

  const loadCandidates = useCallback(
    (fs?: FilterSet | null) => {
      return listCandidates(jobId, fs ? { filter: JSON.stringify(fs) } : undefined).then((res) => {
        setCandidates(res.candidates);
        return res.candidates;
      });
    },
    [jobId],
  );

  const refresh = useCallback(() => {
    Promise.all([getJob(jobId), getRubric(jobId), loadCandidates(activeFilterRef.current)])
      .then(([j, r]) => {
        setJob(j);
        setRubricState(r);
        if (r) setEditedCriteria(r.criteria.map((c) => ({ ...c })));
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/");
          return;
        }
        setError("Couldn't load this job's screening data.");
      });
  }, [jobId, router, loadCandidates]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current);
    },
    [],
  );

  const weightTotalPct = Math.round(editedCriteria.reduce((sum, c) => sum + c.weight, 0) * 100);
  const weightIsBalanced = weightTotalPct === 100;

  function updateWeight(id: string, pct: number) {
    setEditedCriteria((prev) => prev.map((c) => (c.id === id ? { ...c, weight: pct / 100 } : c)));
  }

  function deleteCriterion(id: string) {
    setEditedCriteria((prev) => prev.filter((c) => c.id !== id));
  }

  async function saveRubric() {
    setSavingRubric(true);
    setError("");
    try {
      await applyRubric(jobId, { version: rubric?.version ?? 1, criteria: editedCriteria });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the rubric.");
    } finally {
      setSavingRubric(false);
    }
  }

  async function sendChatMessage() {
    if (!chatInput.trim()) return;
    setChatLoading(true);
    setError("");
    try {
      const res = await rubricChat(jobId, chatInput.trim(), proposedRubric ?? undefined);
      setChatReply(res.reply);
      setChatDiff(res.diff);
      setProposedRubric(res.proposed_rubric);
      setChatInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Copilot couldn't process that.");
    } finally {
      setChatLoading(false);
    }
  }

  async function applyProposedRubric() {
    if (!proposedRubric) return;
    setSavingRubric(true);
    setError("");
    try {
      await applyRubric(jobId, proposedRubric);
      setChatOpen(false);
      setChatReply(null);
      setChatDiff(null);
      setProposedRubric(null);
      setChatInput("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't apply the proposed rubric.");
    } finally {
      setSavingRubric(false);
    }
  }

  function startScan() {
    setError("");
    scanCandidates(jobId)
      .then(() => {
        setScanning(true);
        pollRef.current = setInterval(async () => {
          const list = await loadCandidates(activeFilterRef.current);
          const stillWorking = list.some((c) => c.status === "PARSING" || c.status === "SCORING");
          if (!stillWorking) {
            setScanning(false);
            if (pollRef.current) clearInterval(pollRef.current);
          }
        }, 2500);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Couldn't start scanning.");
      });
  }

  function toggleSelectAll() {
    setSelectedIds(selectedIds.size === candidates.length ? new Set() : new Set(candidates.map((c) => c.id)));
  }

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSort(key: Exclude<SortKey, null>) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function sortIndicator(key: SortKey) {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  // The API already returns candidates ranked desc by overall score -- capture that as a
  // stable per-candidate rank BEFORE any column sort, so the percentile-based green/red
  // coloring always reflects true rank position, never the currently displayed sort order.
  const rankedCandidates = useMemo(() => candidates.map((c, i) => ({ ...c, _rankIndex: i })), [candidates]);

  const displayedCandidates = useMemo(() => {
    if (!sortKey) return rankedCandidates;
    const list = [...rankedCandidates];
    list.sort((a, b) => {
      let av: string | number;
      let bv: string | number;
      if (sortKey === "name") {
        av = a.name.toLowerCase();
        bv = b.name.toLowerCase();
      } else if (sortKey === "overall") {
        av = a.overall ?? -1;
        bv = b.overall ?? -1;
      } else if (sortKey === "status") {
        av = a.pipeline_status ?? "";
        bv = b.pipeline_status ?? "";
      } else if (sortKey === "flags") {
        av = a.is_overqualified ? 1 : 0;
        bv = b.is_overqualified ? 1 : 0;
      } else {
        av = a.screening_decision === "rejected" ? 1 : 0;
        bv = b.screening_decision === "rejected" ? 1 : 0;
      }
      if (av === bv) return 0;
      const cmp = av < bv ? -1 : 1;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return list;
  }, [rankedCandidates, sortKey, sortDir]);

  const selectedCandidates = candidates.filter((c) => selectedIds.has(c.id));
  const canReject = selectedCandidates.some((c) => c.screening_decision !== "rejected");
  const canUnreject = selectedCandidates.some((c) => c.screening_decision === "rejected");

  async function bulkReject() {
    setError("");
    try {
      await Promise.all(Array.from(selectedIds).map((id) => rejectCandidate(jobId, id)));
      setSelectedIds(new Set());
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't reject the selected candidates.");
    }
  }

  async function bulkUnreject() {
    setError("");
    try {
      await Promise.all(Array.from(selectedIds).map((id) => unrejectCandidate(jobId, id)));
      setSelectedIds(new Set());
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't undo rejection for the selected candidates.");
    }
  }

  async function applyFilterText() {
    if (!filterInput.trim()) return;
    setFilterLoading(true);
    setError("");
    try {
      const fs = await parseFilters(jobId, filterInput.trim());
      activeFilterRef.current = fs;
      setActiveFilterSet(fs);
      setUnparsedFragments(fs.unparsed);
      await loadCandidates(fs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't parse that filter.");
    } finally {
      setFilterLoading(false);
    }
  }

  function clearFilters() {
    activeFilterRef.current = null;
    setActiveFilterSet(null);
    setUnparsedFragments([]);
    setFilterInput("");
    loadCandidates(null);
  }

  return (
    <>
      <Navbar />
      <main className="page">
        <button className="link-back" onClick={() => router.push(`/jobs/${jobId}`)}>
          ← Back to job
        </button>

        <div className="page-header">
          <div>
            <h1>Resume Screening{job ? ` — ${job.title}` : ""}</h1>
            <p className="page-subtitle">Review the scoring rubric, scan candidates, and rank them.</p>
          </div>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        {!rubric && (
          <div className="empty-state">
            <p>No rubric yet — upload a job description on the job page first.</p>
          </div>
        )}

        {rubric && (
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
              <p className="section-label" style={{ margin: 0 }}>
                Scoring rubric (v{rubric.version})
              </p>
              <span className={`weight-total ${weightIsBalanced ? "weight-total-ok" : "weight-total-off"}`}>
                Total: {weightTotalPct}%
              </span>
            </div>

            {!weightIsBalanced && (
              <div className="alert alert-warning" style={{ marginTop: "0.75rem" }}>
                Weights currently {weightTotalPct > 100 ? "add up to more than" : "fall short of"} 100%
                (they total {weightTotalPct}%). That&apos;s fine — they&apos;ll be automatically rebalanced
                proportionally to sum to 100% when you save.
              </div>
            )}

            <ul className="rubric-list">
              {editedCriteria.map((c) => (
                <li key={c.id} className="rubric-row">
                  <div className="rubric-row-main">
                    <div className="rubric-row-name">{c.name}</div>
                    {(() => {
                      const anchors = parseAnchors(c.description);
                      if (!anchors) return <p className="rubric-row-desc">{c.description}</p>;
                      return (
                        <div className="rubric-anchor-list">
                          {anchors.map((a) => (
                            <div
                              key={a.level}
                              className={`rubric-anchor rubric-anchor-${a.label.toLowerCase().replace(/\s+/g, "-")}`}
                            >
                              <span className="rubric-anchor-label">{a.label}:</span> {a.text}
                            </div>
                          ))}
                        </div>
                      );
                    })()}
                  </div>
                  <div className="rubric-row-controls">
                    <label className="weight-input">
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={Math.round(c.weight * 100)}
                        onChange={(e) => updateWeight(c.id, Number(e.target.value))}
                        aria-label={`Weight for ${c.name}`}
                      />
                      <span className="weight-input-suffix">%</span>
                    </label>
                    <button
                      className="icon-delete-btn"
                      onClick={() => deleteCriterion(c.id)}
                      title={`Remove "${c.name}"`}
                      aria-label={`Remove ${c.name}`}
                    >
                      ✕
                    </button>
                  </div>
                </li>
              ))}
            </ul>

            <div className="wizard-actions">
              <button
                className="btn btn-primary"
                onClick={saveRubric}
                disabled={savingRubric || editedCriteria.length === 0}
              >
                {savingRubric ? "Saving…" : "Save changes"}
              </button>
              <button className="btn btn-secondary" onClick={() => setChatOpen((v) => !v)}>
                Fine-tune with AI
              </button>
              <button className="btn btn-secondary" onClick={startScan} disabled={scanning}>
                {scanning ? "Scanning…" : "Start resume scanning"}
              </button>
            </div>

            {chatOpen && (
              <div className="card" style={{ marginTop: "1rem" }}>
                <p className="section-label">Fine-tune rubric</p>
                <p className="page-subtitle">
                  Describe the change you want — e.g. &quot;add a criterion for chaos engineering&quot; or
                  &quot;drop the mentorship criterion and reweight the rest&quot;.
                </p>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <input
                    type="text"
                    className="text-input"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && sendChatMessage()}
                    placeholder="Type an instruction…"
                    style={{ flex: 1 }}
                  />
                  <button className="btn btn-primary" onClick={sendChatMessage} disabled={chatLoading}>
                    {chatLoading ? "Thinking…" : "Send"}
                  </button>
                </div>

                {chatReply && (
                  <div className="alert alert-success" style={{ marginTop: "0.75rem" }}>
                    {chatReply}
                  </div>
                )}

                {chatDiff && proposedRubric && (
                  <>
                    <ul style={{ listStyle: "none", padding: 0, margin: "0.75rem 0", display: "grid", gap: "0.5rem" }}>
                      {proposedRubric.criteria.map((c) => (
                        <li key={c.id}>
                          <strong>{c.name}</strong> — {Math.round(c.weight * 100)}%
                          {chatDiff.added.some((a) => a.id === c.id) && (
                            <span className="badge badge-success" style={{ marginLeft: "0.5rem" }}>
                              new
                            </span>
                          )}
                          {chatDiff.edited_descriptions.includes(c.id) && (
                            <span className="badge badge-warning" style={{ marginLeft: "0.5rem" }}>
                              edited
                            </span>
                          )}
                        </li>
                      ))}
                      {chatDiff.removed.map((id) => (
                        <li key={id} style={{ textDecoration: "line-through", color: "var(--text-muted)" }}>
                          {id} — removed
                        </li>
                      ))}
                    </ul>
                    <div className="wizard-actions">
                      <button className="btn btn-primary" onClick={applyProposedRubric} disabled={savingRubric}>
                        {savingRubric ? "Applying…" : "Apply this change"}
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {candidates.length > 0 && (
          <div className="card">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "0.5rem",
              }}
            >
              <p className="section-label">{candidates.length} candidates</p>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <input
                  type="text"
                  className="text-input"
                  value={filterInput}
                  onChange={(e) => setFilterInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && applyFilterText()}
                  placeholder='e.g. "5+ years in Mumbai with strong kubernetes"'
                  style={{ width: "22rem" }}
                />
                <button className="btn btn-secondary" onClick={applyFilterText} disabled={filterLoading}>
                  {filterLoading ? "Filtering…" : "Filter"}
                </button>
                {activeFilterSet && (
                  <button className="btn btn-secondary" onClick={clearFilters}>
                    Clear
                  </button>
                )}
              </div>
            </div>

            {activeFilterSet && activeFilterSet.filters.length > 0 && (
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", margin: "0.5rem 0" }}>
                {activeFilterSet.filters.map((f, i) => (
                  <span key={i} className="badge badge-neutral">
                    {f.field} {f.op} {f.criterion_id ? `(${f.criterion_id}) ` : ""}
                    {Array.isArray(f.value) ? f.value.join(", ") : String(f.value)}
                  </span>
                ))}
              </div>
            )}

            {unparsedFragments.length > 0 && (
              <div className="alert alert-warning">Couldn&apos;t map to a filter: {unparsedFragments.join(", ")}</div>
            )}

            <div className="wizard-actions">
              <button className="btn btn-danger" onClick={bulkReject} disabled={!canReject}>
                Reject selected ({selectedIds.size})
              </button>
              <button className="btn btn-secondary" onClick={bulkUnreject} disabled={!canUnreject}>
                Unreject selected
              </button>
            </div>

            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        className="grid-checkbox"
                        checked={selectedIds.size > 0 && selectedIds.size === candidates.length}
                        onChange={toggleSelectAll}
                        title="Select all"
                      />
                    </th>
                    <th className="sortable" onClick={() => toggleSort("name")}>
                      Candidate{sortIndicator("name")}
                    </th>
                    <th className="sortable" onClick={() => toggleSort("overall")}>
                      Overall{sortIndicator("overall")}
                    </th>
                    <th className="sortable" onClick={() => toggleSort("status")}>
                      Status{sortIndicator("status")}
                    </th>
                    <th className="sortable" onClick={() => toggleSort("flags")}>
                      Flags{sortIndicator("flags")}
                    </th>
                    <th className="sortable" onClick={() => toggleSort("decision")}>
                      Decision{sortIndicator("decision")}
                    </th>
                    <th>HR Screening</th>
                  </tr>
                </thead>
                <tbody>
                  {displayedCandidates.map((c) => (
                    <tr
                      key={c.id}
                      onClick={() => router.push(`/jobs/${jobId}/candidates/${c.id}`)}
                      className={c.is_overqualified ? "row-overqualified" : undefined}
                      style={{ cursor: "pointer" }}
                    >
                      <td onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          className="grid-checkbox"
                          checked={selectedIds.has(c.id)}
                          onChange={() => toggleSelect(c.id)}
                        />
                      </td>
                      <td>
                        <div className="cand-name">{c.name}</div>
                        <div className="cand-email">{c.email}</div>
                      </td>
                      <td>
                        {c.overall != null ? (
                          <span className={`score-pill ${scoreClassForRank(c._rankIndex, candidates.length)}`}>
                            {Math.round(c.overall * 100)}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        {c.pipeline_status ? (
                          <span className={`badge ${statusBadgeClass(c.pipeline_status)}`}>{c.pipeline_status}</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        {c.is_overqualified ? (
                          <span
                            className="badge badge-flag"
                            title={c.overqualification_reason || "Recent experience reads more senior than this role."}
                          >
                            ⚠ Overqualified
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        {c.screening_decision === "rejected" ? (
                          <span className="badge badge-warning">Rejected</span>
                        ) : c.screening_session_status ? (
                          <span className="badge badge-active">HR screening sent</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => setScreeningCandidate(c)}
                          disabled={c.screening_decision === "rejected"}
                        >
                          {c.screening_session_status ? "Re-trigger" : "Trigger"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      {screeningCandidate && (
        <TriggerScreeningModal
          jobId={jobId}
          candidateId={screeningCandidate.id}
          candidateName={screeningCandidate.name}
          onClose={() => {
            setScreeningCandidate(null);
            // Refresh so the Decision column reflects a newly-triggered screening.
            refresh();
          }}
        />
      )}
    </>
  );
}

export default function ScreeningPage() {
  return (
    <RequireAuth>
      <ScreeningPageInner />
    </RequireAuth>
  );
}
