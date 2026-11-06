// Story #174: calmer colours, one colour per opportunity type, priority in one hue.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PriorityBadge, TYPE_META, TypeBadge } from "../components/labels";
import { Overview } from "../screens/Overview";
import { DEFINITIONS, OVERVIEW } from "./fixtures";
import { mockApi, renderWithProviders } from "./render";

const TOKENS = readFileSync(join(__dirname, "..", "tokens", "tokens.css"), "utf-8");
const token = (name: string) => TOKENS.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`))![1];

function hsl(hex: string): { h: number; s: number; l: number } {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: (h * 60 + 360) % 360, s, l };
}

describe("AC1 one consistent colour per opportunity type", () => {
  it("each type has its own chart token, and the four are different", () => {
    const colours = Object.values(TYPE_META).map((m) => m.chart);
    expect(new Set(colours).size).toBe(4);
    for (const n of [1, 2, 3, 4]) expect(token(`chart-${n}`)).toMatch(/^#/);
  });

  it("the type pill shows the type's colour as a dot next to its name and icon", () => {
    render(<TypeBadge type="dormancy" />);
    const dot = screen.getByText("Dormant customer").parentElement!.querySelector("[data-type-dot]") as HTMLElement;
    expect(dot.style.backgroundColor).toBe(TYPE_META.dormancy.chart);
  });
});

describe("AC2 priority is one hue in three shades, red only for errors", () => {
  it("high, medium and low share a hue and get lighter", () => {
    const [high, medium, low] = ["priority-high", "priority-medium", "priority-low"].map((n) => hsl(token(n)));
    expect(Math.abs(high.h - medium.h)).toBeLessThan(15);
    expect(Math.abs(medium.h - low.h)).toBeLessThan(15);
    expect(high.l).toBeLessThan(medium.l);
    expect(medium.l).toBeLessThan(low.l);
    expect(token("priority-high")).not.toBe(token("danger"));
  });

  it("the priority pills are not red or amber", () => {
    render(<><PriorityBadge level="High" /><PriorityBadge level="Medium" /></>);
    for (const level of ["High", "Medium"]) {
      expect(screen.getByText(level).className).not.toMatch(/danger|warn/);
    }
  });
});

describe("AC4 the value chart shows the range", () => {
  it("the summary names the low-to-high range with the money unit", async () => {
    mockApi({ "/overview": OVERVIEW, "/definitions": DEFINITIONS });
    renderWithProviders(<Overview />);
    expect(await screen.findByRole("region", { name: "Value range by type (estimate)" })).toBeInTheDocument();
    expect(screen.getByText(/has the largest value estimate: .+ to .+ net sales\./)).toBeInTheDocument();
  });
});
