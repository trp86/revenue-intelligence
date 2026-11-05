// Every number on a screen renders through Metric (spec 07 section 6): one formatter, its
// unit, and a button that opens its definition (mouse or keyboard). In a dense table the
// definition can sit once in the column header instead (DefinitionButton, story #149).
import { Info } from "lucide-react";
import { useId, useState } from "react";

import type { Metric as MetricValue } from "../api/types";
import { formatValue, unitLabel } from "../format";
import { useDefinition } from "./Definitions";

/** The info button that opens a definition, closed again by Escape or a second press. */
export function DefinitionButton({ definitionId, label }: { definitionId: string; label: string }) {
  const [open, setOpen] = useState(false);
  const definition = useDefinition(definitionId);
  const panel = useId();
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        aria-label={`Definition of ${label}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-full text-muted hover:text-primary"
      >
        <Info className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      {open && (
        <span
          id={panel}
          role="tooltip"
          className="absolute left-0 top-full z-dialog mt-1 w-72 rounded border border-border bg-surface p-2 text-left text-xs font-normal normal-case tracking-normal text-text shadow-md"
        >
          {definition?.text ?? "No definition found."}
        </span>
      )}
    </span>
  );
}

interface Props {
  metric: Pick<MetricValue, "unit" | "definition_id"> & { value: number | string | null };
  label?: string;
  className?: string;
  /** Leave out the unit when a column header already names it. */
  hideUnit?: boolean;
  /** Leave out the definition button when the column header carries it. */
  hideDefinition?: boolean;
}

export function Metric({ metric, label, className, hideUnit = false, hideDefinition = false }: Props) {
  const unit = unitLabel(metric.unit);
  return (
    <span className={`relative inline-flex items-baseline gap-1 ${className ?? ""}`}>
      <span className="tabular-nums">{formatValue(metric.value, metric.unit)}</span>
      {unit && !hideUnit && <span className="text-xs text-muted">{unit}</span>}
      {!hideDefinition && (
        <DefinitionButton definitionId={metric.definition_id} label={label ?? metric.definition_id} />
      )}
    </span>
  );
}
