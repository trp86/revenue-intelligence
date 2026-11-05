// The filters (story #149): native selects (labelled, keyboard friendly) and a branch search
// applied on Enter or when the field loses focus.
import { Search } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "../../lib/utils";

export interface Option {
  value: string;
  label: string;
}

const control =
  "h-10 w-full cursor-pointer rounded-md border border-border-strong bg-surface px-3 text-sm text-text";

export function FilterSelect({
  label,
  value,
  options,
  onChange,
  allLabel = "All",
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (v: string) => void;
  allLabel?: string | null;
}) {
  return (
    <label className="flex min-w-36 flex-col gap-1 text-sm">
      <span className="font-medium text-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={control}>
        {allLabel !== null && <option value="">{allLabel}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function BranchSearch({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <div className="flex min-w-44 flex-col gap-1 text-sm">
      <label htmlFor="branch-search" className="font-medium text-muted">Branch</label>
      <span className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" />
        <input
          id="branch-search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => text.trim() !== value && onChange(text.trim())}
          onKeyDown={(e) => e.key === "Enter" && onChange(text.trim())}
          placeholder="e.g. Magway"
          aria-describedby="branch-help"
          className={cn(control, "cursor-text pl-9")}
        />
      </span>
      <span id="branch-help" className="sr-only">Press Enter to apply.</span>
    </div>
  );
}
