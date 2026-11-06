// Labels that never rely on colour alone (spec 07 section 7): text, a Lucide icon and a token
// colour. Shared by every screen (story #148 replaced the Unicode symbols with icons).
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowUp,
  LayoutGrid,
  Minus,
  SignalHigh,
  SignalLow,
  SignalMedium,
  TrendingDown,
  UserX,
  type LucideIcon,
} from "lucide-react";

import type { Level, OppType } from "../api/types";
import { Badge } from "./ui/badge";

export const TYPE_LABEL: Record<OppType, string> = {
  dormancy: "Dormant customer",
  recovery: "Revenue recovery",
  whitespace: "Category whitespace",
  crosssell: "Cross-sell",
};

/** Short names for dense tables and chart axes; the full name stays in titles and tooltips. */
export const TYPE_SHORT: Record<OppType, string> = {
  dormancy: "Dormant",
  recovery: "Recovery",
  whitespace: "Whitespace",
  crosssell: "Cross-sell",
};

/** Per engine: its icon and its chart colour token (one per engine, never the only signal). */
export const TYPE_META: Record<OppType, { icon: LucideIcon; chart: string }> = {
  crosssell: { icon: ArrowLeftRight, chart: "var(--color-chart-1)" },
  whitespace: { icon: LayoutGrid, chart: "var(--color-chart-2)" },
  dormancy: { icon: UserX, chart: "var(--color-chart-3)" },
  recovery: { icon: TrendingDown, chart: "var(--color-chart-4)" },
};

export const PRIORITY_COLOR: Record<Level, string> = {
  High: "var(--color-priority-high)",
  Medium: "var(--color-priority-medium)",
  Low: "var(--color-priority-low)",
};

// priority pills are calm (story #174): one neutral pill, told apart by text, icon and a shade swatch
const PRIORITY: Record<Level, { icon: LucideIcon; tone: "neutral" }> = {
  High: { icon: ArrowUp, tone: "neutral" },
  Medium: { icon: Minus, tone: "neutral" },
  Low: { icon: ArrowDown, tone: "neutral" },
};

const CONFIDENCE: Record<Level, LucideIcon> = { High: SignalHigh, Medium: SignalMedium, Low: SignalLow };

export function TypeBadge({ type, short = false }: { type: OppType; short?: boolean }) {
  const Icon = TYPE_META[type].icon;
  return (
    <Badge tone="neutral" className="w-fit whitespace-nowrap" title={short ? TYPE_LABEL[type] : undefined}>
      {/* the type's colour, the same in every chart and tab (story #174); text stays in ink */}
      <span data-type-dot aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: TYPE_META[type].chart }} />
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {short ? TYPE_SHORT[type] : TYPE_LABEL[type]}
    </Badge>
  );
}

export function PriorityBadge({ level }: { level: Level }) {
  const { icon: Icon, tone } = PRIORITY[level];
  return (
    <Badge tone={tone} data-level={level} className={level === "High" ? "font-semibold" : undefined}>
      <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-sm" style={{ backgroundColor: PRIORITY_COLOR[level] }} />
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {level}
    </Badge>
  );
}

export function ConfidenceBadge({ level }: { level: Level }) {
  const Icon = CONFIDENCE[level];
  return (
    <span className="inline-flex items-center gap-1 text-sm text-muted" data-level={level}>
      <Icon className="h-4 w-4" aria-hidden="true" />
      {level}
    </span>
  );
}

export function customerLabel(customer: { code: string | null; name: string | null }): string {
  return [customer.name, customer.code].filter(Boolean).join(" · ") || "Unknown customer";
}
