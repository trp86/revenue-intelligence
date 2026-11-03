// Labels that never rely on colour alone (spec 07 section 7): text, an icon and a token colour.
import type { Level, OppType } from "../api/types";

export const TYPE_LABEL: Record<OppType, string> = {
  dormancy: "Dormant customer",
  recovery: "Revenue recovery",
  whitespace: "Category whitespace",
  crosssell: "Cross-sell",
};

const PRIORITY_ICON: Record<Level, string> = { High: "▲", Medium: "■", Low: "▽" };
const PRIORITY_CLASS: Record<Level, string> = {
  High: "text-priority-high",
  Medium: "text-priority-medium",
  Low: "text-priority-low",
};

export function PriorityBadge({ level }: { level: Level }) {
  return (
    <span className={`inline-flex items-center gap-1 font-semibold ${PRIORITY_CLASS[level]}`}>
      <span aria-hidden="true">{PRIORITY_ICON[level]}</span>
      {level}
    </span>
  );
}

export function ConfidenceBadge({ level }: { level: Level }) {
  return (
    <span className="inline-flex items-center gap-1 text-muted">
      <span aria-hidden="true">{level === "High" ? "●●●" : level === "Medium" ? "●●○" : "●○○"}</span>
      {level}
    </span>
  );
}

export function customerLabel(customer: { code: string | null; name: string | null }): string {
  return [customer.name, customer.code].filter(Boolean).join(" · ") || "Unknown customer";
}
