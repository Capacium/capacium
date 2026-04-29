import { Suspense } from "react";
import Link from "next/link";
import { getStats, getCategories, getRecentCapabilities } from "@/lib/api";
import SearchBar from "@/components/SearchBar";
import CapabilityCard from "@/components/CapabilityCard";
import type { Stats, Category } from "@/lib/types";
import type { CapabilityResult } from "@/lib/types";

function StatsBarSkeleton() {
  return (
    <div className="grid grid-cols-3 gap-6">
      {[1, 2, 3].map((i) => (
        <div key={i} className="bg-bg-secondary border border-border rounded-xl p-6 text-center animate-pulse">
          <div className="h-8 w-16 bg-bg-tertiary rounded mx-auto mb-2" />
          <div className="h-4 w-20 bg-bg-tertiary rounded mx-auto" />
        </div>
      ))}
    </div>
  );
}

function CategoriesSkeleton() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="h-16 bg-bg-secondary border border-border rounded-xl animate-pulse" />
      ))}
    </div>
  );
}

function CardsSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-40 bg-bg-secondary border border-border rounded-xl animate-pulse" />
      ))}
    </div>
  );
}

async function StatsSection() {
  let stats: Stats | null = null;
  try {
    stats = await getStats();
  } catch {
    // stats unavailable
  }

  if (!stats) return null;

  return (
    <div className="grid grid-cols-3 gap-6">
      <div className="bg-bg-secondary border border-border rounded-xl p-6 text-center">
        <div className="text-3xl font-bold text-accent">{stats.capabilities.toLocaleString()}</div>
        <div className="text-sm text-text-secondary mt-1">Capabilities</div>
      </div>
      <div className="bg-bg-secondary border border-border rounded-xl p-6 text-center">
        <div className="text-3xl font-bold text-purple">{stats.publishers.toLocaleString()}</div>
        <div className="text-sm text-text-secondary mt-1">Publishers</div>
      </div>
      <div className="bg-bg-secondary border border-border rounded-xl p-6 text-center">
        <div className="text-3xl font-bold text-green">{stats.frameworks.toLocaleString()}</div>
        <div className="text-sm text-text-secondary mt-1">Frameworks</div>
      </div>
    </div>
  );
}

async function CategoriesGrid() {
  let categories: Category[] = [];
  try {
    categories = await getCategories();
  } catch {
    // categories unavailable
  }

  if (!categories.length) return null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
      {categories.map((cat) => (
        <Link
          key={cat.slug}
          href={`/search?category=${encodeURIComponent(cat.slug)}`}
          className="bg-bg-secondary border border-border rounded-xl p-4 hover:border-accent hover:-translate-y-0.5 transition-all group text-center"
        >
          <div className="text-2xl mb-1">
            {cat.slug === "ai-ml" ? "🧠" :
             cat.slug === "dev-tools" ? "🛠️" :
             cat.slug === "productivity" ? "⚡" :
             cat.slug === "web" ? "🌐" :
             cat.slug === "data" ? "📊" :
             cat.slug === "security" ? "🔒" :
             cat.slug === "testing" ? "🧪" :
             cat.slug === "design" ? "🎨" : "📦"}
          </div>
          <div className="text-sm font-medium text-text-primary group-hover:text-accent transition-colors">
            {cat.name}
          </div>
          {cat.count != null && (
            <div className="text-xs text-text-muted mt-0.5">
              {cat.count.toLocaleString()}
            </div>
          )}
        </Link>
      ))}
    </div>
  );
}

async function RecentSection() {
  let results: CapabilityResult[] = [];
  try {
    const res = await getRecentCapabilities();
    results = res.results || [];
  } catch {
    // recent unavailable
  }

  if (!results.length) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {results.map((cap) => (
        <CapabilityCard key={`${cap.owner}/${cap.name}`} cap={cap} />
      ))}
    </div>
  );
}

export default function LandingPage() {
  return (
    <main>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-border">
        <div className="max-w-[1400px] mx-auto px-6 py-20 lg:py-28 text-center">
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold text-text-primary tracking-tight">
            Discover AI Agent
            <span className="block text-accent">Capabilities</span>
          </h1>
          <p className="mt-4 text-lg text-text-secondary max-w-lg mx-auto">
            Search, install, and share agent capabilities across frameworks
          </p>
          <div className="mt-8 max-w-xl mx-auto">
            <Suspense fallback={<div className="h-11 bg-bg-tertiary rounded-lg animate-pulse" />}>
              <SearchBar placeholder="Search capabilities, publishers, frameworks..." autoFocus />
            </Suspense>
          </div>
          <div className="mt-6 flex items-center justify-center gap-3 text-sm text-text-muted">
            <span className="text-accent font-mono">cap install</span>
            <span>owner/name</span>
            <Link href="/search" className="text-text-secondary hover:text-accent transition-colors underline underline-offset-2">
              or browse all
            </Link>
          </div>
        </div>
        {/* subtle gradient bg */}
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-accent/5 via-transparent to-transparent" />
      </section>

      {/* Stats */}
      <section className="max-w-[1400px] mx-auto px-6 py-16">
        <Suspense fallback={<StatsBarSkeleton />}>
          <StatsSection />
        </Suspense>
      </section>

      {/* Categories */}
      <section className="max-w-[1400px] mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-text-primary mb-6">Categories</h2>
        <Suspense fallback={<CategoriesSkeleton />}>
          <CategoriesGrid />
        </Suspense>
      </section>

      {/* Recent */}
      <section className="max-w-[1400px] mx-auto px-6 pb-16">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-text-primary">Recent Capabilities</h2>
          <Link
            href="/search?sort=recent"
            className="text-sm text-accent hover:text-accent-hover transition-colors"
          >
            View all →
          </Link>
        </div>
        <Suspense fallback={<CardsSkeleton />}>
          <RecentSection />
        </Suspense>
      </section>

      {/* Footer */}
      <footer className="border-t border-border">
        <div className="max-w-[1400px] mx-auto px-6 py-8 text-center text-sm text-text-muted">
          Capacium Marketplace — Capability Packaging System
        </div>
      </footer>
    </main>
  );
}
