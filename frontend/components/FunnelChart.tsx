import type { FunnelStage } from "@/lib/types";

export default function FunnelChart({ stages, total }: { stages: FunnelStage[]; total: number }) {
  const max = Math.max(total, 1);

  return (
    <div className="funnel">
      <div className="funnel-row">
        <div className="funnel-label">Applied</div>
        <div className="funnel-bar-track">
          <div className="funnel-bar funnel-bar-total" style={{ width: "100%" }} />
        </div>
        <div className="funnel-count">{total}</div>
      </div>
      {stages.map((s) => (
        <div key={s.round_key} className="funnel-row">
          <div className="funnel-label">{s.name}</div>
          <div className="funnel-bar-track">
            <div className="funnel-bar" style={{ width: `${Math.max((s.count / max) * 100, s.count > 0 ? 4 : 0)}%` }} />
          </div>
          <div className="funnel-count">{s.count}</div>
        </div>
      ))}
    </div>
  );
}
