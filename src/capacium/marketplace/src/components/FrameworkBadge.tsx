const FRAMEWORK_COLORS: Record<string, string> = {
  opencode: "bg-accent/15 text-accent border-accent/30",
  "claude-code": "bg-purple/15 text-purple border-purple/30",
  "gemini-cli": "bg-cyan/15 text-cyan border-cyan/30",
  cursor: "bg-orange/15 text-orange border-orange/30",
  "continue.dev": "bg-pink/15 text-pink border-pink/30",
};

export default function FrameworkBadge({ framework }: { framework: string }) {
  const colors =
    FRAMEWORK_COLORS[framework] ||
    "bg-bg-tertiary text-text-secondary border-border";
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-[11px] font-medium border ${colors}`}
    >
      {framework}
    </span>
  );
}
