"use client";

import { useMemo, useState } from "react";

import { exportCandidates, rejectCandidate, shortlistCandidate, unrejectCandidate, unshortlistCandidate } from "@/lib/api";
import { statusBadgeClass } from "@/lib/status";
import type { LeaderboardCandidate, LeaderboardResponse } from "@/lib/types";

type SortKey = "name" | "external_id" | "status" | "source" | "application_date" | "overall" | string;
type SortDir = "asc" | "desc";

function scoreClass(score: number): string {
  if (score >= 80) return "score-high";
  if (score >= 60) return "score-mid";
  return "score-low";
}

export interface LeaderboardRowAction {
  label: string;
  onClick: (candidate: LeaderboardCandidate) => void;
  disabled?: (candidate: LeaderboardCandidate) => boolean;
}

export default function Leaderboard({
  data,
  jobId,
  onRowClick,
  onRefresh,
  rowAction,
  readOnly = false,
}: {
  data: LeaderboardResponse;
  jobId: number | string;
  onRowClick?: (candidate: LeaderboardCandidate) => void;
  onRefresh?: () => void | Promise<void>;
  rowAction?: LeaderboardRowAction;
  readOnly?: boolean;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("overall");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [filterRound, setFilterRound] = useState<string>("overall");
  const [minScore, setMinScore] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState("");

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function scoreFor(c: LeaderboardCandidate, key: string): number | null {
    if (key === "overall") return c.overall;
    return c.round_scores.find((r) => r.round_key === key)?.score ?? null;
  }

  const filtered = useMemo(() => {
    const threshold = minScore.trim() === "" ? null : Number(minScore);
    return data.candidates.filter((c) => {
      if (threshold === null || Number.isNaN(threshold)) return true;
      const value = scoreFor(c, filterRound);
      return value !== null && value >= threshold;
    });
  }, [data.candidates, filterRound, minScore]);

  const sorted = useMemo(() => {
    const list = [...filtered];
    list.sort((a, b) => {
      let av: string | number | null;
      let bv: string | number | null;
      if (sortKey === "name") {
        av = a.name;
        bv = b.name;
      } else if (sortKey === "external_id") {
        av = a.external_id ?? "";
        bv = b.external_id ?? "";
      } else if (sortKey === "status") {
        av = a.status;
        bv = b.status;
      } else if (sortKey === "source") {
        av = a.source_type ?? "";
        bv = b.source_type ?? "";
      } else if (sortKey === "application_date") {
        av = a.application_date ?? "";
        bv = b.application_date ?? "";
      } else {
        av = scoreFor(a, sortKey);
        bv = scoreFor(b, sortKey);
        // nulls sort last regardless of direction
        if (av === null && bv === null) return 0;
        if (av === null) return 1;
        if (bv === null) return -1;
      }
      if (av === bv) return 0;
      const cmp = av! < bv! ? -1 : 1;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return list;
  }, [filtered, sortKey, sortDir]);

  function sortIndicator(key: SortKey) {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  const byId = useMemo(() => new Map(data.candidates.map((c) => [c.id, c])), [data.candidates]);
  const selectedCandidates = useMemo(
    () => Array.from(selectedIds).map((id) => byId.get(id)).filter((c): c is LeaderboardCandidate => Boolean(c)),
    [selectedIds, byId],
  );
  const allSelectedRejected =
    selectedCandidates.length > 0 && selectedCandidates.every((c) => c.screening_decision === "rejected");
  const allSelectedShortlisted =
    selectedCandidates.length > 0 && selectedCandidates.every((c) => c.screening_decision === "shortlisted");

  function toggleSelectAll() {
    setSelectedIds(selectedIds.size === sorted.length ? new Set() : new Set(sorted.map((c) => c.id)));
  }

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runBulk(action: (id: number) => Promise<unknown>, errorMsg: string) {
    setBulkBusy(true);
    setBulkError("");
    try {
      await Promise.all(Array.from(selectedIds).map((id) => action(id)));
      setSelectedIds(new Set());
      await onRefresh?.();
    } catch (err) {
      setBulkError(err instanceof Error ? err.message : errorMsg);
    } finally {
      setBulkBusy(false);
    }
  }

  function handleShortlistAction() {
    if (allSelectedShortlisted) {
      runBulk((id) => unshortlistCandidate(jobId, id), "Couldn't undo shortlisting for the selected candidates.");
    } else {
      runBulk((id) => shortlistCandidate(jobId, id), "Couldn't shortlist the selected candidates.");
    }
  }

  function handleRejectAction() {
    if (allSelectedRejected) {
      runBulk((id) => unrejectCandidate(jobId, id), "Couldn't undo rejection for the selected candidates.");
    } else {
      runBulk((id) => rejectCandidate(jobId, id), "Couldn't reject the selected candidates.");
    }
  }

  const decisionBadge = (decision: string | null) => {
    if (decision === "shortlisted") return <span className="badge badge-success">Shortlisted</span>;
    if (decision === "rejected") return <span className="badge badge-warning">Rejected</span>;
    return "—";
  };

  async function handleExport() {
    setExportBusy(true);
    setExportError("");
    try {
      const { blob, filename } = await exportCandidates(jobId, sorted.map((c) => c.id));
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Couldn't export candidates.");
    } finally {
      setExportBusy(false);
    }
  }

  return (
    <div>
      <div className="leaderboard-toolbar">
        <div className="leaderboard-filter">
          <span className="section-label" style={{ margin: 0 }}>
            Filter
          </span>
          <select value={filterRound} onChange={(e) => setFilterRound(e.target.value)}>
            <option value="overall">Overall score</option>
            {data.rounds.map((r) => (
              <option key={r.round_key} value={r.round_key}>
                {r.name}
              </option>
            ))}
          </select>
          <span className="page-subtitle" style={{ margin: 0 }}>
            &ge;
          </span>
          <input
            type="number"
            className="leaderboard-filter-input"
            placeholder="score"
            value={minScore}
            onChange={(e) => setMinScore(e.target.value)}
          />
          {minScore.trim() !== "" && (
            <button className="link-back" style={{ margin: 0 }} onClick={() => setMinScore("")}>
              Clear
            </button>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span className="page-subtitle" style={{ margin: 0 }}>
            {sorted.length} of {data.candidates.length} candidates
            {!readOnly && selectedIds.size > 0 ? ` · ${selectedIds.size} selected` : ""}
          </span>
          <button className="btn btn-small btn-secondary" onClick={handleExport} disabled={exportBusy}>
            {exportBusy ? "Exporting…" : "Export to Excel"}
          </button>
        </div>
      </div>

      {exportError && <div className="alert alert-error">{exportError}</div>}

      {!readOnly && (
        <div className="wizard-actions">
          <button
            className="btn btn-success"
            onClick={handleShortlistAction}
            disabled={selectedIds.size === 0 || bulkBusy}
          >
            {allSelectedShortlisted
              ? `Unshortlist selected (${selectedIds.size})`
              : `Shortlist selected (${selectedIds.size})`}
          </button>
          <button
            className="btn btn-danger"
            onClick={handleRejectAction}
            disabled={selectedIds.size === 0 || bulkBusy}
          >
            {allSelectedRejected ? `Unreject selected (${selectedIds.size})` : `Reject selected (${selectedIds.size})`}
          </button>
        </div>
      )}

      {!readOnly && bulkError && <div className="alert alert-error">{bulkError}</div>}

      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              {!readOnly && (
                <th>
                  <input
                    type="checkbox"
                    checked={sorted.length > 0 && selectedIds.size === sorted.length}
                    onChange={toggleSelectAll}
                    aria-label="Select all candidates"
                  />
                </th>
              )}
              <th className="sortable" onClick={() => toggleSort("name")}>
                Candidate{sortIndicator("name")}
              </th>
              <th className="sortable" onClick={() => toggleSort("external_id")}>
                ID{sortIndicator("external_id")}
              </th>
              <th className="sortable" onClick={() => toggleSort("status")}>
                Status{sortIndicator("status")}
              </th>
              <th>Decision</th>
              <th className="sortable" onClick={() => toggleSort("source")}>
                Source{sortIndicator("source")}
              </th>
              <th className="sortable" onClick={() => toggleSort("application_date")}>
                Applied{sortIndicator("application_date")}
              </th>
              {data.rounds.map((r) => (
                <th key={r.round_key} className="sortable" onClick={() => toggleSort(r.round_key)}>
                  {r.name}
                  {sortIndicator(r.round_key)}
                </th>
              ))}
              <th className="sortable" onClick={() => toggleSort("overall")}>
                Overall{sortIndicator("overall")}
              </th>
              {rowAction && !readOnly && <th>{rowAction.label}</th>}
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
              <tr key={c.id} onClick={() => onRowClick?.(c)} style={onRowClick ? { cursor: "pointer" } : undefined}>
                {!readOnly && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(c.id)}
                      onChange={() => toggleSelect(c.id)}
                      aria-label={`Select ${c.name}`}
                    />
                  </td>
                )}
                <td>
                  <div className="cand-name">{c.name}</div>
                  <div className="cand-email">{c.email}</div>
                </td>
                <td>{c.external_id ?? "—"}</td>
                <td>
                  <span className={`badge ${statusBadgeClass(c.status)}`}>{c.status}</span>
                </td>
                <td>{decisionBadge(c.screening_decision)}</td>
                <td>
                  {c.source_type || "—"}
                  {c.source_name ? ` · ${c.source_name}` : ""}
                </td>
                <td>{c.application_date || "—"}</td>
                {c.round_scores.map((rs) => (
                  <td key={rs.round_key}>
                    {rs.score != null ? (
                      <span className={`score-pill ${scoreClass(rs.score)}`}>{rs.score}%</span>
                    ) : (
                      "—"
                    )}
                  </td>
                ))}
                <td>
                  {c.overall != null ? (
                    <span className={`score-pill ${scoreClass(c.overall)}`}>{c.overall}%</span>
                  ) : (
                    "—"
                  )}
                </td>
                {rowAction && !readOnly && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <button
                      className="btn btn-small btn-primary"
                      onClick={() => rowAction.onClick(c)}
                      disabled={rowAction.disabled?.(c)}
                    >
                      {rowAction.label}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
