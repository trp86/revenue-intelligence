/** Tailwind maps every colour, radius and font to a design token (src/tokens/tokens.css).
 * No literal colour is allowed in a component: src/test/tokens.test.ts fails on one. */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      bg: "var(--color-bg)",
      surface: "var(--color-surface)",
      border: "var(--color-border)",
      text: "var(--color-text)",
      muted: "var(--color-text-muted)",
      primary: "var(--color-primary)",
      "on-primary": "var(--color-on-primary)",
      measured: "var(--color-measured)",
      "measured-bg": "var(--color-measured-bg)",
      estimate: "var(--color-estimate)",
      "estimate-bg": "var(--color-estimate-bg)",
      ai: "var(--color-ai)",
      "ai-bg": "var(--color-ai-bg)",
      success: "var(--color-success)",
      warn: "var(--color-warn)",
      danger: "var(--color-danger)",
      "priority-high": "var(--color-priority-high)",
      "priority-medium": "var(--color-priority-medium)",
      "priority-low": "var(--color-priority-low)",
      focus: "var(--color-focus)",
    },
    borderRadius: { none: "0", sm: "var(--radius-sm)", DEFAULT: "var(--radius-md)",
      lg: "var(--radius-lg)", full: "9999px" },
    fontFamily: { sans: "var(--font-sans)", mono: "var(--font-mono)" },
    extend: {},
  },
  plugins: [],
};
