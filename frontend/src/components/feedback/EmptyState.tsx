import { Inbox, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/** Nothing to show: say why and what to do (spec 07 section 5). */
export function EmptyState({
  title,
  reason,
  action,
  icon: Icon = Inbox,
}: {
  title: string;
  reason?: ReactNode;
  action?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div role="status" className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-surface px-6 py-10 text-center">
      <Icon className="h-8 w-8 text-muted" aria-hidden="true" />
      <p className="font-heading font-semibold text-text">{title}</p>
      {reason && <p className="max-w-md text-sm text-muted">{reason}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
