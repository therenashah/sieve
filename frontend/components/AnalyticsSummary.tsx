import type { LeaderboardResponse } from "@/lib/types";

export default function AnalyticsSummary({ data }: { data: LeaderboardResponse }) {
  const shortlisted = data.candidates.filter((c) => c.screening_decision === "shortlisted").length;
  const rejected = data.candidates.filter((c) => c.screening_decision === "rejected").length;
  const completed = data.candidates.filter((c) => c.status === "All rounds completed").length;

  const tiles: { label: string; value: number; tone: "neutral" | "success" | "danger" | "info" }[] = [
    { label: "Applied", value: data.total_candidates, tone: "neutral" },
    { label: "Shortlisted", value: shortlisted, tone: "success" },
    { label: "Rejected", value: rejected, tone: "danger" },
    { label: "Completed all rounds", value: completed, tone: "info" },
  ];

  return (
    <div className="stat-grid">
      {tiles.map((t) => (
        <div key={t.label} className={`stat-tile stat-tile-${t.tone}`}>
          <div className="stat-tile-value">{t.value}</div>
          <div className="stat-tile-label">{t.label}</div>
        </div>
      ))}
    </div>
  );
}
