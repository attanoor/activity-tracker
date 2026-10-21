import type { Config } from "tailwindcss";

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("bg"), surface: token("surface"), line: token("line"), fg: token("fg"),
        muted: token("muted"), accent: token("accent"), "accent-fg": token("accent-fg"),
        danger: token("danger"), ok: token("ok"),
      },
      fontFamily: { sans: ["Segoe UI", "system-ui", "sans-serif"], mono: ["Consolas", "ui-monospace", "monospace"] },
    },
  },
} satisfies Config;
