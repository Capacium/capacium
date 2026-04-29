"use client";

import { useState } from "react";

export default function InstallBox({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  return (
    <div className="flex items-center justify-between gap-3 p-4 bg-bg-primary border border-border rounded-lg">
      <code className="text-sm text-accent font-mono select-all">{command}</code>
      <button
        onClick={handleCopy}
        className={`px-3 py-1 text-xs rounded-md border font-medium transition-colors whitespace-nowrap ${
          copied
            ? "bg-trust-signed/15 text-trust-signed border-trust-signed"
            : "bg-bg-tertiary border-border text-text-secondary hover:bg-bg-hover hover:text-text-primary"
        }`}
      >
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}
