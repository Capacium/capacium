import { getCapability } from "@/lib/api";
import TrustBadge from "@/components/TrustBadge";
import TrustProgression from "@/components/TrustProgression";
import ScoreBreakdown from "@/components/ScoreBreakdown";
import FrameworkBadge from "@/components/FrameworkBadge";
import InstallBox from "@/components/InstallBox";
import Link from "next/link";
import { notFound } from "next/navigation";

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

export default async function CapabilityDetailPage({
  params,
}: {
  params: Promise<{ owner: string; name: string }>;
}) {
  const { owner, name } = await params;

  let cap;
  try {
    cap = await getCapability(owner, name);
  } catch {
    notFound();
  }

  const capId = `${cap.owner}/${cap.name}`;
  const installCmd = `cap install ${capId}`;

  return (
    <main className="max-w-[1000px] mx-auto px-6 py-8">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm text-text-muted mb-6">
        <Link href="/" className="hover:text-text-primary transition-colors">
          Home
        </Link>
        <span>/</span>
        <Link href={`/publisher/${encodeURIComponent(cap.owner)}`} className="hover:text-text-primary transition-colors">
          {cap.owner}
        </Link>
        <span>/</span>
        <span className="text-text-primary">{cap.name}</span>
      </nav>

      {/* Header */}
      <div className="bg-bg-secondary border border-border rounded-xl p-6 mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
          <div>
            <h1 className="text-2xl font-bold text-text-primary">{cap.name}</h1>
            <p className="text-sm text-text-muted font-mono mt-1">{capId}</p>
          </div>
          <span
            className={`flex-shrink-0 text-[10px] font-semibold uppercase tracking-wide px-2.5 py-1 rounded-full ${
              KIND_COLORS[cap.kind] || "bg-bg-tertiary text-text-secondary"
            }`}
          >
            {cap.kind}
          </span>
        </div>

        <p className="text-text-secondary leading-relaxed mb-4">
          {cap.description || "No description provided."}
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <TrustBadge trust={cap.trust} />
          <span className="text-xs text-text-secondary font-mono">v{cap.version}</span>
          {cap.installs != null && (
            <span className="text-xs text-text-muted">
              {cap.installs.toLocaleString()} installs
            </span>
          )}
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main content */}
        <div className="lg:col-span-2 space-y-6">
          {/* Trust Progression */}
          <section className="bg-bg-secondary border border-border rounded-xl p-6">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
              Trust
            </h2>
            <TrustProgression trust={cap.trust} />
          </section>

          {/* Score Breakdown */}
          {cap.trust_score && (
            <section className="bg-bg-secondary border border-border rounded-xl p-6">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
                Score
              </h2>
              <ScoreBreakdown score={cap.trust_score} />
            </section>
          )}

          {/* Frameworks */}
          {cap.frameworks && cap.frameworks.length > 0 && (
            <section className="bg-bg-secondary border border-border rounded-xl p-6">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-3">
                Compatible Frameworks
              </h2>
              <div className="flex flex-wrap gap-2">
                {cap.frameworks.map((f) => (
                  <FrameworkBadge key={f} framework={f} />
                ))}
              </div>
            </section>
          )}

          {/* Dependencies */}
          <section className="bg-bg-secondary border border-border rounded-xl p-6">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-3">
              Dependencies
            </h2>
            {cap.dependencies && Object.keys(cap.dependencies).length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {Object.entries(cap.dependencies).map(([dep, ver]) => (
                  <span
                    key={dep}
                    className="inline-block px-3 py-1 bg-bg-tertiary rounded-md font-mono text-xs text-text-secondary"
                  >
                    {dep} {ver && <span className="text-text-muted">{ver}</span>}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-sm text-text-muted">None</span>
            )}
          </section>

          {/* Version History */}
          {cap.versions && cap.versions.length > 0 && (
            <section className="bg-bg-secondary border border-border rounded-xl p-6">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-3">
                Version History
              </h2>
              <div className="space-y-2">
                {cap.versions.map((v, i) => (
                  <div
                    key={v.version}
                    className="flex items-center justify-between py-2 px-3 bg-bg-tertiary rounded-md"
                  >
                    <span className={`font-mono text-sm ${i === 0 ? "text-text-primary font-semibold" : "text-text-secondary"}`}>
                      v{v.version}
                      {i === 0 && (
                        <span className="ml-2 text-[10px] uppercase text-trust-signed font-sans">
                          latest
                        </span>
                      )}
                    </span>
                    {v.published_at && (
                      <span className="text-xs text-text-muted">
                        {new Date(v.published_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Fingerprint */}
          {cap.fingerprint && (
            <section className="bg-bg-secondary border border-border rounded-xl p-6">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-3">
                Fingerprint
              </h2>
              <code className="text-xs text-text-muted font-mono break-all">
                {cap.fingerprint}
              </code>
            </section>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Install */}
          <section className="bg-bg-secondary border border-border rounded-xl p-6 sticky top-[73px]">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-3">
              Install
            </h2>
            <InstallBox command={installCmd} />

            <div className="mt-4 space-y-3">
              {/* Publisher link */}
              <Link
                href={`/publisher/${encodeURIComponent(cap.owner)}`}
                className="block p-3 bg-bg-tertiary rounded-lg hover:bg-bg-hover transition-colors"
              >
                <div className="text-[10px] uppercase tracking-wider text-text-muted">
                  Publisher
                </div>
                <div className="text-sm font-medium text-text-primary mt-0.5 flex items-center gap-2">
                  <div className="w-5 h-5 rounded-full bg-accent/20 flex items-center justify-center text-[10px] text-accent font-bold">
                    {cap.owner.charAt(0).toUpperCase()}
                  </div>
                  {cap.owner}
                </div>
              </Link>

              {/* Details */}
              <div className="p-3 bg-bg-tertiary rounded-lg space-y-2">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-muted">
                    Kind
                  </div>
                  <div className="text-sm text-text-primary capitalize">{cap.kind}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-muted">
                    Version
                  </div>
                  <div className="text-sm text-text-primary font-mono">v{cap.version}</div>
                </div>
                {cap.updated_at && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-text-muted">
                      Updated
                    </div>
                    <div className="text-sm text-text-primary">
                      {new Date(cap.updated_at).toLocaleDateString()}
                    </div>
                  </div>
                )}
              </div>

              {/* Per-framework install */}
              {cap.frameworks && cap.frameworks.length > 0 && (
                <div className="space-y-2">
                  <div className="text-[10px] uppercase tracking-wider text-text-muted px-1">
                    Per-framework commands
                  </div>
                  {cap.frameworks.map((f) => (
                    <InstallBox key={f} command={`cap install ${capId} --framework ${f}`} />
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
