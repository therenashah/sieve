// Single source of truth for styling a candidate's pipeline status label. The label
// text itself comes from the backend's pipeline_status_label() (see routes_jobs.py) —
// this only maps that text to a badge color, kept here so every page that renders a
// pipeline status (leaderboard, candidate detail, round pages) looks the same.
export function statusBadgeClass(status: string): string {
  if (status.includes("pending")) return "badge-warning";
  if (status === "All rounds completed") return "badge-success";
  return "badge-neutral";
}
