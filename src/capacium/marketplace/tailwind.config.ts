import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        "bg-primary": "#0d1117",
        "bg-secondary": "#161b22",
        "bg-tertiary": "#21262d",
        "bg-hover": "#30363d",
        border: "#30363d",
        "text-primary": "#e6edf3",
        "text-secondary": "#8b949e",
        "text-muted": "#6e7681",
        accent: "#58a6ff",
        "accent-hover": "#79c0ff",
        green: "#3fb950",
        orange: "#d29922",
        purple: "#bc8cff",
        pink: "#f778ba",
        cyan: "#56d4dd",
        red: "#f85149",
        "trust-discovered": "#6e7681",
        "trust-audited": "#d29922",
        "trust-verified": "#58a6ff",
        "trust-signed": "#3fb950",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: ['"SFMono-Regular"', "Consolas", '"Liberation Mono"', "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
