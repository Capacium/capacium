"use client";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="max-w-[1400px] mx-auto px-6 py-20 text-center">
      <div className="text-4xl mb-3 opacity-50 text-text-muted">⚠</div>
      <h1 className="text-2xl font-bold text-text-primary mb-2">Something went wrong</h1>
      <p className="text-text-secondary mb-6 text-sm">{error.message || "An unexpected error occurred"}</p>
      <button
        onClick={reset}
        className="inline-flex px-4 py-2 bg-accent text-white rounded-lg text-sm font-medium hover:bg-accent-hover transition-colors"
      >
        Try again
      </button>
    </main>
  );
}
