"use client";

import { useMemo, useState } from "react";

import type { LeaderboardCandidate, LeaderboardResponse } from "@/lib/types";

type SortKey = "name" | "external_id" | "status" | "source" | "application_date" | "overall" | string;
type SortDir = "asc" | "desc";

function scoreClass(score: number): string {
  if (score >= 80) return "score-high";
  if (score >= 60) return "score-mid";
  return "score-low";
}

function statusBadgeClass(status: string): string {
  if (status.includes("pending")) return "badge-warning";
  if (status === "All rounds completed") return "badge-success";
  if (status === "Not started") return "badge-neutral";
  return "badge-neutral";
}

export default function Leaderboard({
  data,
  onRowClick,
}: {
  data: LeaderboardResponse;
  onRowClick?: (candidate: LeaderboardCandidate) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("overall");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [filterRound, setFilterRound] = useState<string>("overall");
  const [minScore, setMinScore] = useState("");

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
        <span className="page-subtitle" style={{ margin: 0 }}>
          {sorted.length} of {data.candidates.length} candidates
        </span>
      </div>

      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th className="sortable" onClick={() => toggleSort("name")}>
                Candidate{sortIndicator("name")}
              </th>
              <th className="sortable" onClick={() => toggleSort("external_id")}>
                ID{sortIndicator("external_id")}
              </th>
              <th className="sortable" onClick={() => toggleSort("status")}>
                Status{sortIndicator("status")}
              </th>
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
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
              <tr key={c.id} onClick={() => onRowClick?.(c)} style={onRowClick ? { cursor: "pointer" } : undefined}>
                <td>
                  <div className="cand-name">{c.name}</div>
                  <div className="cand-email">{c.email}</div>
                </td>
                <td>{c.external_id ?? "—"}</td>
                <td>
                  <span className={`badge ${statusBadgeClass(c.status)}`}>{c.status}</span>
                </td>
                <td>
                  {c.source_type || "—"}
                  {c.source_name ? ` · ${c.source_name}` : ""}
                </td>
                <td>{c.application_date || "—"}</td>
                {c.round_scores.map((rs) => (
                  <td key={rs.round_key}>
                    {rs.score != null ? (
                      <span className={`score-pill ${scoreClass(rs.score)}`}>{rs.score}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                ))}
                <td>
                  {c.overall != null ? (
                    <span className={`score-pill ${scoreClass(c.overall)}`}>{c.overall}</span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
