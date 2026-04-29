import type { TrustLevel } from "@/lib/types";

const STEPS: { level: TrustLevel; label: string }[] = [
  { level: "discovered", label: "Discovered" },
  { level: "audited", label: "Audited" },
  { level: "verified", label: "Verified" },
  { level: "signed", label: "Signed" },
];

const COLORS: Record<TrustLevel, string> = {
  discovered: "bg-trust-discovered",
  audited: "bg-trust-audited",
  verified: "bg-trust-verified",
  signed: "bg-trust-signed",
};

const BORDER_COLORS: Record<TrustLevel, string> = {
  discovered: "border-trust-discovered",
  audited: "border-trust-audited",
  verified: "border-trust-verified",
  signed: "border-trust-signed",
};

export default function TrustProgression({ trust }: { trust?: TrustLevel }) {
  const current = trust || "discovered";
  const currentIdx = STEPS.findIndex((s) => s.level === current);

  return (
    <div className="flex items-center gap-0.5">
      {STEPS.map((step, i) => {
        const active = i <= currentIdx;
        const isCurrent = i === currentIdx;
        return (
          <div key={step.level} className="flex items-center gap-0.5">
            <div
              className={`w-3 h-3 rounded-full border-2 transition-colors ${
                active
                  ? `${COLORS[step.level]} ${BORDER_COLORS[step.level]}`
                  : "bg-transparent border-trust-discovered"
              } ${isCurrent ? "ring-2 ring-offset-1 ring-offset-bg-secondary ring-white/20" : ""}`}
              title={step.label}
            />
            {i < STEPS.length - 1 && (
              <div
                className={`w-6 h-0.5 transition-colors ${
                  i < currentIdx ? COLORS[STEPS[i + 1].level] : "bg-bg-tertiary"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
