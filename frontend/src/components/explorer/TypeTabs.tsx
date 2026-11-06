// Quick switch between the engines (story #149): a group of toggle buttons with aria-pressed.
import type { OppType } from "../../api/types";
import { cn } from "../../lib/utils";
import { TYPE_LABEL, TYPE_META } from "../labels";

const ORDER: (OppType | undefined)[] = [undefined, "dormancy", "recovery", "whitespace", "crosssell"];

export function TypeTabs({ value, onChange }: { value?: OppType; onChange: (t?: OppType) => void }) {
  return (
    <div role="group" aria-label="Opportunity type" className="flex flex-wrap gap-2">
      {ORDER.map((type) => {
        const active = type === value;
        const Icon = type ? TYPE_META[type].icon : null;
        return (
          <button
            key={type ?? "all"}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(type)}
            className={cn(
              "inline-flex h-9 cursor-pointer items-center gap-2 rounded-full border px-4 text-sm font-medium transition-colors duration-fast",
              active
                ? "border-opportunity bg-opportunity text-on-primary"
                : "border-border bg-surface text-text hover:border-border-strong",
            )}
          >
            {type && (
              // the type's colour, as in the charts and pills (story #174)
              <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full ring-1 ring-surface"
                style={{ backgroundColor: TYPE_META[type].chart }} />
            )}
            {Icon && <Icon className="h-4 w-4" aria-hidden="true" />}
            {type ? TYPE_LABEL[type] : "All types"}
          </button>
        );
      })}
    </div>
  );
}
