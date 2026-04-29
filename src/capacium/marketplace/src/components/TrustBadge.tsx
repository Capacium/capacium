import type { TrustLevel } from "@/lib/types";

const TRUST_CONFIG: Record<
  TrustLevel,
  { label: string; bg: string; text: string; icon: string }
> = {
  discovered: { label: "Discovered", bg: "bg-trust-discovered/15", text: "text-trust-discovered", icon: "○" },
  audited: { label: "Audited", bg: "bg-trust-audited/15", text: "text-trust-audited", icon: "◐" },
  verified: { label: "Verified", bg: "bg-trust-verified/15", text: "text-trust-verified", icon: "◑" },
  signed: { label: "Signed", bg: "bg-trust-signed/15", text: "text-trust-signed", icon: "●" },
};

export default function TrustBadge({ trust }: { trust?: TrustLevel }) {
  const level = trust || "discovered";
  const c = TRUST_CONFIG[level];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${c.bg} ${c.text}`}
      title={`Trust: ${c.label}`}
    >
      <span className="text-[10px]">{c.icon}</span>
      {c.label}
    </span>
  );
}
