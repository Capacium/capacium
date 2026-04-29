import { getPublisher, searchCapabilities } from "@/lib/api";
import CapabilityCard from "@/components/CapabilityCard";
import Link from "next/link";
import { notFound } from "next/navigation";

export default async function PublisherPage({
  params,
}: {
  params: Promise<{ owner: string }>;
}) {
  const { owner } = await params;

  let pub;
  try {
    pub = await getPublisher(owner);
  } catch {
    notFound();
  }

  // If the publisher endpoint doesn't return capabilities inline,
  // search for them separately
  let capabilities = pub.capabilities;
  if (!capabilities || !capabilities.length) {
    try {
      const res = await searchCapabilities({ q: "", per_page: 50 });
      capabilities = (res.results || []).filter(
        (c) => c.owner === owner
      );
    } catch {
      capabilities = [];
    }
  }

  return (
    <main className="max-w-[1000px] mx-auto px-6 py-8">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm text-text-muted mb-6">
        <Link href="/" className="hover:text-text-primary transition-colors">
          Home
        </Link>
        <span>/</span>
        <span className="text-text-primary">{owner}</span>
      </nav>

      {/* Publisher Header */}
      <div className="bg-bg-secondary border border-border rounded-xl p-6 mb-8">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-accent/20 flex items-center justify-center text-2xl text-accent font-bold flex-shrink-0">
            {owner.charAt(0).toUpperCase()}
          </div>
          <div>
            <h1 className="text-2xl font-bold text-text-primary">{owner}</h1>
            <p className="text-sm text-text-muted font-mono mt-0.5">
              @{owner}
            </p>
          </div>
        </div>

        {/* Aggregate trust */}
        {pub.aggregate_trust != null && (
          <div className="mt-4 pt-4 border-t border-border">
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted uppercase tracking-wider">
                Aggregate Trust
              </span>
              <span
                className={`text-lg font-bold ${
                  pub.aggregate_trust >= 80
                    ? "text-trust-signed"
                    : pub.aggregate_trust >= 60
                      ? "text-trust-verified"
                      : pub.aggregate_trust >= 40
                        ? "text-trust-audited"
                        : "text-trust-discovered"
                }`}
              >
                {Math.round(pub.aggregate_trust)}%
              </span>
            </div>
          </div>
        )}

        <div className="flex items-center gap-4 mt-4 pt-4 border-t border-border">
          <div className="text-center">
            <div className="text-lg font-semibold text-text-primary">
              {capabilities.length}
            </div>
            <div className="text-xs text-text-muted">Capabilities</div>
          </div>
        </div>
      </div>

      {/* Capabilities */}
      <h2 className="text-xl font-semibold text-text-primary mb-4">
        Capabilities by {owner}
      </h2>

      {capabilities.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {capabilities.map((cap) => (
            <CapabilityCard key={`${cap.owner}/${cap.name}`} cap={cap} />
          ))}
        </div>
      ) : (
        <div className="text-center py-16 text-text-muted">
          <div className="text-4xl mb-3 opacity-50">📦</div>
          <div className="text-lg">No capabilities published yet</div>
        </div>
      )}
    </main>
  );
}
