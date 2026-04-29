import Link from "next/link";

export default function Header() {
  return (
    <header className="sticky top-0 z-50 bg-bg-secondary border-b border-border">
      <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center gap-8">
        <Link href="/" className="flex items-center gap-2.5 flex-shrink-0 group">
          <span className="text-2xl">&#9889;</span>
          <div>
            <span className="text-lg font-bold text-text-primary leading-tight block">
              Capacium
            </span>
            <span className="text-[11px] uppercase tracking-widest text-text-secondary">
              Marketplace
            </span>
          </div>
        </Link>

        <nav className="flex items-center gap-1 ml-auto">
          <Link
            href="/search"
            className="px-3 py-1.5 text-sm text-text-secondary hover:text-text-primary rounded-md hover:bg-bg-tertiary transition-colors"
          >
            Browse
          </Link>
        </nav>
      </div>
    </header>
  );
}
