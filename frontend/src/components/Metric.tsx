// Every number on a screen renders through Metric (spec 07 section 6): one formatter, its
// unit, and a button that opens its definition (mouse or keyboard). In a dense table the
// definition can sit once in the column header instead (DefinitionButton, story #149).
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";

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

const PANEL_WIDTH = 288; // px; never below 240 on a narrow screen
const GAP = 8; // px between the panel and the button or the viewport edge
const ROOM_BELOW = 160; // px needed below the button, else the panel opens above it

/** Where the panel goes: under the button, shifted to stay in the viewport, above if no room. */
export function placePanel(rect: Pick<DOMRect, "left" | "top" | "bottom">): CSSProperties {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.max(240, Math.min(PANEL_WIDTH, vw - 2 * GAP));
  const left = Math.max(GAP, Math.min(rect.left, vw - width - GAP));
  const vertical = vh - rect.bottom < ROOM_BELOW && rect.top > ROOM_BELOW
    ? { bottom: vh - rect.top + 4 }
    : { top: rect.bottom + 4 };
  return { left, width, ...vertical };
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
  const [position, setPosition] = useState<CSSProperties>({});
  const button = useRef<HTMLButtonElement>(null);
  const definition = useDefinition(definitionId);
  const panel = useId();
  // The panel is portalled to <body> with a fixed position, so a scrolling table cannot clip it
  // (story #162); it follows the button on scroll and resize while open.
  useLayoutEffect(() => {
    if (!open) return;
    const update = () => button.current && setPosition(placePanel(button.current.getBoundingClientRect()));
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open]);
  return (
    <span className="relative inline-flex">
      <button
        ref={button}
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
      {open &&
        createPortal(
          <span
            id={panel}
            role="tooltip"
            style={position}
            className="fixed z-dialog block rounded border border-border bg-surface p-2 text-left text-xs font-normal normal-case tracking-normal text-text shadow-md"
          >
            {definition?.text ?? "No definition found."}
            {unit === "net sales" && <NetSalesSource />}
          </span>,
          // inside <main> so it stays in a landmark; fixed, so no scroll container clips it
          document.getElementById("main") ?? document.body,
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
