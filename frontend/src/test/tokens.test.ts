// Story #135 AC2 and AC3: design tokens only, and only the API client calls the network.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const TOKEN_FILE = join(SRC, "tokens", "tokens.css");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

const SOURCE = files(SRC).filter((f) => /\.(tsx?|css)$/.test(f) && !f.includes(".test."));
// a hex colour of 3, 6 or 8 digits with at least one letter (so "story #135" is not one), or a
// colour function
const COLOUR =
  /#(?=[0-9]*[a-fA-F])(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|\b(?:rgb|rgba|hsl|hsla)\s*\(/;

describe("AC2 design tokens", () => {
  it("has no literal colour outside the token file", () => {
    const offenders = SOURCE.filter((f) => f !== TOKEN_FILE)
      .filter((f) => COLOUR.test(readFileSync(f, "utf-8")))
      .map((f) => relative(SRC, f));
    expect(offenders).toEqual([]);
  });

  it("defines the semantic tokens", () => {
    const tokens = readFileSync(TOKEN_FILE, "utf-8");
    for (const name of ["measured", "estimate", "ai", "priority-high", "priority-medium",
      "priority-low", "success", "warn", "danger"]) {
      expect(tokens).toContain(`--color-${name}:`);
    }
  });
});

describe("AC3 only the API client calls the network", () => {
  it("calls fetch only in src/api/client.ts", () => {
    const callers = SOURCE.filter((f) => /\bfetch\s*\(/.test(readFileSync(f, "utf-8")))
      .map((f) => relative(SRC, f).replaceAll("\\", "/"));
    expect(callers.filter((f) => !f.startsWith("test/"))).toEqual(["api/client.ts"]);
  });

  it("imports no DuckDB or Gemini SDK", () => {
    const pkg = readFileSync(join(SRC, "..", "package.json"), "utf-8");
    for (const banned of ["duckdb", "@google/genai", "@google/generative-ai"]) {
      expect(pkg).not.toContain(banned);
    }
    for (const file of SOURCE) {
      expect(readFileSync(file, "utf-8")).not.toMatch(/from ["'](?:duckdb|@google\/)/);
    }
  });
});
