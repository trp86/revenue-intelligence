// Every number on a screen renders through Metric (spec 07 section 6): one formatter, its
// unit, and a button that opens its definition (mouse or keyboard). In a dense table the
// definition can sit once in the column header instead (DefinitionButton, story #149).
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { useId, useState } from "react";

import { api } from "../api/client";
import type { Metric as MetricValue } from "../api/types";
import { formatKpi, formatValue, unitLabel } from "../format";
import { useDefinition } from "./Definitions";

/** Which source column net sales is taken from, for net sales values (story #161). */
function NetSalesSource() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  if (!health.data?.net_sales_field) return null;
  return (
    <span className="mt-1 block text-muted">
      Net sales are taken from {health.data.net_sales_field}
      {health.data.net_sales_provisional ? " (provisional)" : ""}.
    </span>
  );
}

/** The info button that opens a definition, closed again by Escape or a second press. */
export function DefinitionButton({
  definitionId,
  label,
  unit,
}: {
  definitionId: string;
  label: string;
  /** The value's unit; a net sales value also names the source field. */
  unit?: string;
}) {
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
          {unit === "net sales" && <NetSalesSource />}
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
  /** Show values of 1 billion or more in compact form (4.49B), the full value in the title (#159). */
  compact?: boolean;
}

const BILLION = 1_000_000_000;

export function Metric({
  metric,
  label,
  className,
  hideUnit = false,
  hideDefinition = false,
  compact = false,
}: Props) {
  const unit = unitLabel(metric.unit);
  const full = formatValue(metric.value, metric.unit);
  const short = compact && typeof metric.value === "number" && Math.abs(metric.value) >= BILLION;
  return (
    <span data-metric className={`relative inline-flex items-baseline gap-1 ${className ?? ""}`}>
      {short ? (
        <>
          <span className="tabular-nums" title={full} aria-hidden="true">{formatKpi(metric.value as number)}</span>
          <span className="sr-only">({full})</span>
        </>
      ) : (
        <span className="tabular-nums">{full}</span>
      )}
      {unit && !hideUnit && <span className="text-xs text-muted">{unit}</span>}
      {!hideDefinition && (
        <DefinitionButton definitionId={metric.definition_id} label={label ?? metric.definition_id} unit={metric.unit} />
      )}
    </span>
  );
}
