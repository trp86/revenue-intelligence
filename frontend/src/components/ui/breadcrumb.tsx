import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

export interface Crumb {
  label: string;
  to?: string;
}

/** Breadcrumbs: the last item is the current page (aria-current), the rest are links. */
export function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-1 text-sm text-muted">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} className="flex items-center gap-1">
              {item.to && !last ? (
                <Link to={item.to} className="rounded-sm hover:text-text hover:underline">
                  {item.label}
                </Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={last ? "font-medium text-text" : ""}>
                  {item.label}
                </span>
              )}
              {!last && <ChevronRight className="h-4 w-4" aria-hidden="true" />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
