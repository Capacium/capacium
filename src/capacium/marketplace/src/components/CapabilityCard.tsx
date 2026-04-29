import type { CapabilityResult } from "@/lib/types";
import TrustBadge from "./TrustBadge";
import FrameworkBadge from "./FrameworkBadge";
import Link from "next/link";

const KIND_COLORS: Record<string, string> = {
  skill: "bg-accent/15 text-accent",
  bundle: "bg-purple/15 text-purple",
  tool: "bg-green/15 text-green",
  prompt: "bg-orange/15 text-orange",
  template: "bg-cyan/15 text-cyan",
  workflow: "bg-pink/15 text-pink",
  "mcp-server": "bg-red/15 text-red",
  "connector-pack": "bg-yellow-600/15 text-yellow-500",
};

export default function CapabilityCard({ cap }: { cap: CapabilityResult }) {
  const href =
    cap.owner && cap.name
      ? `/capability/${encodeURIComponent(cap.owner)}/${encodeURIComponent(cap.name)}`
      : "#";
  const displayName = cap.owner ? `${cap.owner}/${cap.name}` : cap.name;
  const desc = cap.description || "No description provided.";

  return (
    <Link
      href={href}
      className="block bg-bg-secondary border border-border rounded-xl p-5 hover:border-accent hover:-translate-y-0.5 transition-all group"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-text-primary truncate group-hover:text-accent transition-colors">
            {displayName}
          </h3>
          <p className="text-xs text-text-muted mt-0.5 font-mono">
            v{cap.version}
          </p>
        </div>
        <span
          className={`flex-shrink-0 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full ${
            KIND_COLORS[cap.kind] || "bg-bg-tertiary text-text-secondary"
          }`}
        >
          {cap.kind}
        </span>
      </div>

      <p className="text-sm text-text-secondary line-clamp-2 mb-3 leading-relaxed">
        {desc}
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <TrustBadge trust={cap.trust} />
        {cap.installs != null && (
          <span className="text-[11px] text-text-muted">
            {cap.installs.toLocaleString()} installs
          </span>
        )}
      </div>

      {cap.frameworks && cap.frameworks.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {cap.frameworks.map((f) => (
            <FrameworkBadge key={f} framework={f} />
          ))}
        </div>
      )}
    </Link>
  );
}
