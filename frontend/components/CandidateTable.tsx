"use client";

import { useState } from "react";

import TriggerScreeningModal from "@/components/TriggerScreeningModal";
import type { Candidate } from "@/lib/types";

function scoreClass(score: number): string {
  if (score >= 80) return "score-high";
  if (score >= 60) return "score-mid";
  return "score-low";
}

function ScreeningActionCell({ candidate }: { candidate: Candidate }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        className="btn btn-small btn-primary"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        Trigger HR screening
      </button>
      {open && (
        <TriggerScreeningModal
          jobId={candidate.job_id}
          candidateId={candidate.id}
          candidateName={candidate.name}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

export default function CandidateTable({
  candidates,
  onRowClick,
  showScreeningAction = false,
}: {
  candidates: Candidate[];
  onRowClick?: (candidate: Candidate) => void;
  showScreeningAction?: boolean;
}) {
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Candidate</th>
            <th>ID</th>
            <th>Match score</th>
            <th>Status</th>
            <th>Source</th>
            <th>Applied</th>
            <th>CV</th>
            {showScreeningAction && <th>HR Screening</th>}
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr
              key={c.id}
              onClick={() => onRowClick?.(c)}
              style={onRowClick ? { cursor: "pointer" } : undefined}
            >
              <td>
                <div className="cand-name">{c.name}</div>
                <div className="cand-email">{c.email}</div>
              </td>
              <td>{c.external_id ?? "—"}</td>
              <td>
                {c.match_score != null ? (
                  <span className={`score-pill ${scoreClass(c.match_score)}`}>{c.match_score}</span>
                ) : (
                  "—"
                )}
              </td>
              <td>
                <span className="badge badge-neutral">{c.overall_status || "—"}</span>
              </td>
              <td>
                {c.source_type || "—"}
                {c.source_name ? ` · ${c.source_name}` : ""}
              </td>
              <td>{c.application_date || "—"}</td>
              <td>
                {c.resume_path ? (
                  <span className="badge badge-success">On file</span>
                ) : (
                  <span className="badge badge-warning">Missing</span>
                )}
              </td>
              {showScreeningAction && (
                <td onClick={(e) => e.stopPropagation()}>
                  <ScreeningActionCell candidate={c} />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
