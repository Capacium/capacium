import Link from "next/link";

export default function NotFound() {
  return (
    <main className="max-w-[1400px] mx-auto px-6 py-20 text-center">
      <div className="text-6xl mb-4 opacity-30 text-text-muted">404</div>
      <h1 className="text-2xl font-bold text-text-primary mb-2">Page Not Found</h1>
      <p className="text-text-secondary mb-6">
        The capability or page you are looking for does not exist.
      </p>
      <Link
        href="/"
        className="inline-flex px-4 py-2 bg-accent text-white rounded-lg text-sm font-medium hover:bg-accent-hover transition-colors"
      >
        Back to Marketplace
      </Link>
    </main>
  );
}
