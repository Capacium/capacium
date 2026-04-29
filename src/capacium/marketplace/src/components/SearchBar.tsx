"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";

export default function SearchBar({
  className = "",
  placeholder = "Search capabilities...",
  autoFocus = false,
}: {
  className?: string;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const [value, setValue] = useState(params.get("q") || "");

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = value.trim();
      if (trimmed) {
        router.push(`/search?q=${encodeURIComponent(trimmed)}`);
      } else {
        router.push("/search");
      }
    },
    [value, router]
  );

  return (
    <form onSubmit={handleSubmit} className={`relative ${className}`}>
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="w-full px-4 py-2.5 pl-10 bg-bg-tertiary border border-border rounded-lg text-text-primary text-sm placeholder:text-text-muted focus:outline-none focus:border-accent transition-colors"
      />
      <svg
        className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <circle cx="11" cy="11" r="8" />
        <path d="m21 21-4.35-4.35" />
      </svg>
    </form>
  );
}
