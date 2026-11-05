// Every source file is UTF-8 without mojibake: a non-ASCII character written through a cp1252
// round trip (for example "—" becoming "â€”" or "·" becoming "Â·") fails here. Story #148 found
// and repaired such text in format.ts, AsyncBoundary, AiBrief, labels and Metric.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
// a lead byte of UTF-8 (Â Ã â ð) read as cp1252, followed by a cp1252 continuation character
const MOJIBAKE = /[ÂÃâð][\u0080-ÿŒœŠšŸŽžƒˆ˜–-›€™]/u;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe("source encoding", () => {
  it("has no mojibake in any source file", () => {
    const offenders = files(SRC)
      .filter((f) => /\.(tsx?|css)$/.test(f) && !f.endsWith("encoding.test.ts"))
      .filter((f) => MOJIBAKE.test(readFileSync(f, "utf-8")))
      .map((f) => relative(SRC, f));
    expect(offenders).toEqual([]);
  });

  it("shows a real dash and middle dot", async () => {
    const { formatValue } = await import("../format");
    const { customerLabel } = await import("../components/labels");
    expect(formatValue(null, "days")).toBe("—");
    expect(customerLabel({ name: "Shop", code: "C1" })).toBe("Shop · C1");
  });
});
