// Every number on a screen renders through Metric (spec 07 section 6): one formatter, its
// unit, and a button that opens its definition (mouse or keyboard).
import { Info } from "lucide-react";
import { useId, useState } from "react";

import type { Metric as MetricValue } from "../api/types";
import { formatValue, unitLabel } from "../format";
import { useDefinition } from "./Definitions";

interface Props {
  metric: Pick<MetricValue, "unit" | "definition_id"> & { value: number | string | null };
  label?: string;
  className?: string;
  /** Leave out the unit when a column header already names it. */
  hideUnit?: boolean;
}

export function Metric({ metric, label, className, hideUnit = false }: Props) {
  const [open, setOpen] = useState(false);
  const definition = useDefinition(metric.definition_id);
  const panel = useId();
  const unit = unitLabel(metric.unit);
  return (
    <span className={`relative inline-flex items-baseline gap-1 ${className ?? ""}`}>
      <span className="tabular-nums">{formatValue(metric.value, metric.unit)}</span>
      {unit && !hideUnit && <span className="text-xs text-muted">{unit}</span>}
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        aria-label={`Definition of ${label ?? metric.definition_id}`}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-full text-muted hover:text-primary"
      >
        <Info className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      {open && (
        <span
          id={panel}
          role="tooltip"
          className="absolute left-0 top-full z-10 mt-1 w-72 rounded border border-border bg-surface p-2 text-xs text-text shadow"
        >
          {definition?.text ?? "No definition found."}
        </span>
      )}
    </span>
  );
}
