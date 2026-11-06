// Story #171: visual simplification (plain estimate text, no purple, one Google font).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EstimatePanel } from "../components/detail/panels";
import { estimateText } from "../summaries";
import { DETAIL } from "./fixtures";
import { renderWithProviders } from "./render";

const ROOT = join(__dirname, "..", "..");
const TOKENS = readFileSync(join(ROOT, "src", "tokens", "tokens.css"), "utf-8");

describe("AC5 the estimate explains itself in plain words", () => {
  it.each([
    ["dormancy", "Based on 25% to 75% of what this customer bought in the months before going quiet."],
    ["recovery", "Based on 25% to 75% of how much this customer's sales fell compared with last year."],
    ["whitespace", "Based on 25% to 75% of what a typical similar customer spends on this category."],
    ["crosssell", "Based on 25% to 75% of what a typical customer who buys both spends on the second category."],
  ] as const)("%s", (type, text) => {
    expect(estimateText(type, 0.25, 0.75)).toBe(text);
  });

  it("the percentages follow the config factors", () => {
    expect(estimateText("dormancy", 0.1, 0.5)).toMatch(/^Based on 10% to 50% of /);
  });

  it("AC5 AC6 the Estimate block shows the plain text, not the method or 'Not a measured result'", () => {
    renderWithProviders(<EstimatePanel estimate={DETAIL.estimate} type="dormancy" />);
    const block = screen.getByRole("region", { name: "Estimate" });
    expect(within(block).getByText(/^Based on 25% to 75% of what this customer bought/)).toBeInTheDocument();
    expect(block).not.toHaveTextContent("x the gap");
    expect(block).not.toHaveTextContent("Not a measured result");
  });
});

function hue(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max === min) return -1; // grey
  const d = max - min;
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (h * 60 + 360) % 360;
}

describe("no purple", () => {
  it("no token colour is purple (hue 255 to 320 degrees)", () => {
    const purple = [...TOKENS.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})/g)]
      .filter(([, , hex]) => { const h = hue(hex); return h >= 255 && h <= 320; })
      .map(([, name, hex]) => `${name} ${hex}`);
    expect(purple).toEqual([]);
  });
});

describe("one Google font", () => {
  it("headings and text both use Inter, and Plus Jakarta Sans is gone", () => {
    expect(TOKENS).toMatch(/--font-sans:\s*"Inter"/);
    expect(TOKENS).toMatch(/--font-heading:\s*"Inter"/);
    expect(TOKENS).not.toContain("Plus Jakarta");
    const pkg = readFileSync(join(ROOT, "package.json"), "utf-8");
    expect(pkg).not.toContain("plus-jakarta-sans");
    expect(readFileSync(join(ROOT, "src", "main.tsx"), "utf-8")).toContain("@fontsource/inter/700.css");
  });
});
