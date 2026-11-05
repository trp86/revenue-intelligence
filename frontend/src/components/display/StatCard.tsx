// A KPI tile (story #148): an icon badge, a label, the number through Metric, and an optional
// link that opens the Explorer.
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { Metric as MetricValue } from "../../api/types";
import { cn } from "../../lib/utils";
import { Metric } from "../Metric";
import { Card } from "../ui/card";

const TONE = {
  opportunity: "bg-opportunity-bg text-opportunity",
  measured: "bg-measured-bg text-measured",
  warn: "bg-warn-bg text-warn",
} as const;

export function StatCard({
  label,
  metric,
  icon: Icon,
  tone = "opportunity",
  note,
  to,
  linkLabel,
}: {
  label: string;
  metric: MetricValue;
  icon: LucideIcon;
  tone?: keyof typeof TONE;
  note?: ReactNode;
  to?: string;
  linkLabel?: string;
}) {
  return (
    <Card className="flex flex-col gap-3 p-4 md:p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-muted">{label}</span>
        <span className={cn("flex h-10 w-10 items-center justify-center rounded-lg", TONE[tone])}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
      </div>
      <div className="font-heading text-2xl font-bold leading-none text-text md:text-[28px]">
        <Metric metric={metric} label={label} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span>{note}</span>
        {to && (
          <Link to={to} className="rounded-sm font-medium text-primary hover:underline">
            {linkLabel ?? "Open in Explorer"}
          </Link>
        )}
      </div>
    </Card>
  );
}
