import type { TrustScore as TrustScoreType } from "@/lib/types";

const BARS: { key: keyof TrustScoreType; label: string }[] = [
  { key: "schema", label: "Schema" },
  { key: "security", label: "Security" },
  { key: "maintenance", label: "Maintenance" },
  { key: "community", label: "Community" },
  { key: "docs", label: "Docs" },
];

export default function ScoreBreakdown({ score }: { score?: TrustScoreType }) {
  if (!score) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2">
        <span className="text-3xl font-bold text-text-primary">
          {Math.round(score.overall)}%
        </span>
        <span className="text-sm text-text-muted">trust score</span>
      </div>
      <div className="space-y-2">
        {BARS.map(({ key, label }) => {
          const v = score[key] || 0;
          const color =
            v >= 80
              ? "bg-trust-signed"
              : v >= 60
                ? "bg-trust-verified"
                : v >= 40
                  ? "bg-trust-audited"
                  : "bg-trust-discovered";
          return (
            <div key={key} className="flex items-center gap-2">
              <span className="w-20 text-xs text-text-muted">{label}</span>
              <div className="flex-1 h-1.5 bg-bg-tertiary rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${color} transition-all`}
                  style={{ width: `${v}%` }}
                />
              </div>
              <span className="text-xs text-text-secondary w-8 text-right font-mono">
                {v}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
