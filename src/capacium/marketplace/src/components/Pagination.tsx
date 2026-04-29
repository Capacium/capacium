"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

export default function Pagination({ total, page, perPage }: { total: number; page: number; perPage: number }) {
  const router = useRouter();
  const params = useSearchParams();
  const totalPages = Math.max(1, Math.ceil(total / perPage));

  if (totalPages <= 1) return null;

  const buildQuery = useCallback(
    (p: number) => {
      const next = new URLSearchParams(params.toString());
      next.set("page", String(p));
      return next.toString();
    },
    [params]
  );

  const navigate = useCallback(
    (p: number) => {
      router.push(`/search?${buildQuery(p)}`);
    },
    [router, buildQuery]
  );

  const pages: (number | "...")[] = [];
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= page - 1 && i <= page + 1)) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== "...") {
      pages.push("...");
    }
  }

  return (
    <div className="flex items-center justify-center gap-1 mt-8">
      <button
        onClick={() => navigate(page - 1)}
        disabled={page <= 1}
        className="px-3 py-1.5 text-sm rounded-md text-text-secondary hover:bg-bg-tertiary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        Prev
      </button>
      {pages.map((p, i) =>
        p === "..." ? (
          <span key={`dots-${i}`} className="px-2 text-text-muted text-sm">
            ...
          </span>
        ) : (
          <button
            key={p}
            onClick={() => navigate(p)}
            className={`w-8 h-8 text-sm rounded-md transition-colors ${
              p === page
                ? "bg-accent text-white font-semibold"
                : "text-text-secondary hover:bg-bg-tertiary hover:text-text-primary"
            }`}
          >
            {p}
          </button>
        )
      )}
      <button
        onClick={() => navigate(page + 1)}
        disabled={page >= totalPages}
        className="px-3 py-1.5 text-sm rounded-md text-text-secondary hover:bg-bg-tertiary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        Next
      </button>
    </div>
  );
}
