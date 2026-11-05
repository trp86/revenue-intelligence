// The active filters as removable chips, and "Clear all" (story #149).
import { X } from "lucide-react";

import { Button } from "../ui/button";

export interface Chip {
  key: string;
  label: string;
}

export function FilterChips({
  chips,
  onRemove,
  onClear,
}: {
  chips: Chip[];
  onRemove: (key: string) => void;
  onClear: () => void;
}) {
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Active filters" role="group">
      {chips.map((chip) => (
        <span key={chip.key}
          className="inline-flex items-center gap-1 rounded-full bg-opportunity-bg py-1 pl-3 pr-1 text-sm font-medium text-opportunity">
          {chip.label}
          <button
            type="button"
            onClick={() => onRemove(chip.key)}
            aria-label={`Remove filter ${chip.label}`}
            className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-full hover:bg-surface"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </span>
      ))}
      <Button variant="link" size="sm" onClick={onClear}>Clear all</Button>
    </div>
  );
}
