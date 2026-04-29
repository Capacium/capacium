"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

const KINDS = [
  { value: "", label: "All Kinds" },
  { value: "skill", label: "Skill" },
  { value: "mcp-server", label: "MCP Server" },
  { value: "bundle", label: "Bundle" },
  { value: "tool", label: "Tool" },
  { value: "prompt", label: "Prompt" },
  { value: "template", label: "Template" },
  { value: "workflow", label: "Workflow" },
];

const FRAMEWORKS = [
  { value: "", label: "All Frameworks" },
  { value: "opencode", label: "OpenCode" },
  { value: "claude-code", label: "Claude Code" },
  { value: "gemini-cli", label: "Gemini CLI" },
  { value: "cursor", label: "Cursor" },
  { value: "continue.dev", label: "Continue.dev" },
];

const TRUST_LEVELS = [
  { value: "", label: "Any Trust" },
  { value: "audited", label: "Audited+" },
  { value: "verified", label: "Verified+" },
  { value: "signed", label: "Signed" },
];

export default function Filters() {
  const router = useRouter();
  const params = useSearchParams();

  const currentKind = params.get("kind") || "";
  const currentFramework = params.get("framework") || "";
  const currentTrust = params.get("trust") || "";

  const buildQuery = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) {
        next.set(key, value);
      } else {
        next.delete(key);
      }
      next.delete("page");
      return next.toString();
    },
    [params]
  );

  const navigate = useCallback(
    (key: string, value: string) => {
      router.push(`/search?${buildQuery(key, value)}`);
    },
    [router, buildQuery]
  );

  const filterGroup = (
    label: string,
    options: { value: string; label: string }[],
    current: string,
    key: string
  ) => (
    <div className="mb-6">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary mb-2">
        {label}
      </h3>
      <div className="flex flex-col gap-1">
        {options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => navigate(key, opt.value)}
            className={`text-left px-3 py-1.5 rounded-md text-sm transition-colors ${
              current === opt.value
                ? "bg-accent text-white font-semibold"
                : "text-text-secondary hover:bg-bg-tertiary hover:text-text-primary"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <aside className="w-48 flex-shrink-0">
      {filterGroup("Kind", KINDS, currentKind, "kind")}
      {filterGroup("Framework", FRAMEWORKS, currentFramework, "framework")}
      {filterGroup("Trust", TRUST_LEVELS, currentTrust, "trust")}
    </aside>
  );
}
