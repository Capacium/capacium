import { Suspense } from "react";
import { searchCapabilities } from "@/lib/api";
import SearchBar from "@/components/SearchBar";
import CapabilityCard from "@/components/CapabilityCard";
import Filters from "@/components/Filters";
import Pagination from "@/components/Pagination";

function ResultsSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: 9 }).map((_, i) => (
        <div key={i} className="h-40 bg-bg-secondary border border-border rounded-xl animate-pulse" />
      ))}
    </div>
  );
}

async function ResultsSection({ searchParams }: { searchParams: Record<string, string | undefined> }) {
  const q = searchParams.q;
  const kind = searchParams.kind;
  const framework = searchParams.framework;
  const trust = searchParams.trust;
  const page = Number(searchParams.page) || 1;
  const perPage = 12;

  let data;
  let error: string | null = null;
  try {
    data = await searchCapabilities({ q, kind, framework, trust, page, per_page: perPage });
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to fetch";
  }

  if (error) {
    return (
      <div className="text-center py-16 text-text-muted">
        <div className="text-4xl mb-3 opacity-50">⚠</div>
        <div className="text-lg">Failed to load results</div>
        <div className="text-sm mt-1">{error}</div>
      </div>
    );
  }

  if (!data || !data.results.length) {
    return (
      <div className="text-center py-16 text-text-muted">
        <div className="text-4xl mb-3 opacity-50">🔍</div>
        <div className="text-lg">No capabilities found</div>
        <div className="text-sm mt-1">Try adjusting your search or filters</div>
      </div>
    );
  }

  return (
    <>
      <div className="flex items-baseline gap-3 mb-6">
        <span className="text-sm text-text-secondary bg-bg-tertiary px-2.5 py-0.5 rounded-full">
          {data.total.toLocaleString()} results
        </span>
        {q && (
          <span className="text-sm text-text-muted">
            for &ldquo;{q}&rdquo;
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {data.results.map((cap) => (
          <CapabilityCard key={`${cap.owner}/${cap.name}`} cap={cap} />
        ))}
      </div>

      <Pagination total={data.total} page={data.page} perPage={data.per_page} />
    </>
  );
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const resolvedParams = await searchParams;

  return (
    <main className="max-w-[1400px] mx-auto px-6 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-text-primary mb-4">
          Browse Capabilities
        </h1>
        <div className="max-w-xl">
          <Suspense fallback={<div className="h-11 bg-bg-tertiary rounded-lg animate-pulse" />}>
            <SearchBar />
          </Suspense>
        </div>
      </div>

      <div className="flex gap-8">
        <Suspense fallback={null}>
          <Filters />
        </Suspense>

        <div className="flex-1 min-w-0">
          <Suspense fallback={<ResultsSkeleton />} key={JSON.stringify(resolvedParams)}>
            <ResultsSection searchParams={resolvedParams} />
          </Suspense>
        </div>
      </div>
    </main>
  );
}
