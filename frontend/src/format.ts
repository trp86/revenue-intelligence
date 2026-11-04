// The one number formatter (spec 07 section 8). en-US grouping, no currency symbol: amounts are
// labelled "net sales" (provisional).
const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const two = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export function formatValue(value: number | string | null | undefined, unit: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  switch (unit) {
    case "share":
      return `${two.format(value * 100)}%`;
    case "percent":
      return `${two.format(value)}%`;
    case "ratio":
    case "points":
      return two.format(value);
    default:
      return Math.abs(value) >= 100 ? whole.format(value) : two.format(value);
  }
}

export function unitLabel(unit: string): string {
  return ["share", "percent", "points", "ratio", "date"].includes(unit) ? "" : unit;
}

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** Short form for chart axes and labels: 1.2K, 3.4M, 2.1B (the full value is in the table). */
export function formatCompact(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : compact.format(value);
}
