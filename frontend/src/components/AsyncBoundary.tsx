// Loading, empty, error and partial states for every data region (spec 07 section 5).
import type { ReactNode } from "react";

import { ApiError } from "../api/client";

interface Props<T> {
  query: { isPending: boolean; isError: boolean; error: unknown; data: T | undefined;
    refetch: () => unknown };
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  label: string;
  children: (data: T) => ReactNode;
}

export function AsyncBoundary<T>({ query, isEmpty, empty, label, children }: Props<T>) {
  if (query.isPending) {
    return (
      <div role="status" aria-live="polite" aria-busy="true" className="animate-pulse space-y-2">
        <span className="sr-only">Loading {label}â€¦</span>
        <div className="h-4 w-2/3 rounded bg-border" />
        <div className="h-4 w-1/2 rounded bg-border" />
      </div>
    );
  }
  if (query.isError) {
    const message =
      query.error instanceof ApiError ? query.error.message : "Something went wrong.";
    return (
      <div role="alert" className="rounded border border-danger bg-surface p-4">
        <p className="font-semibold text-danger">âš  Could not load {label}</p>
        <p className="mt-1 text-sm text-muted">{message}</p>
        <button
          type="button"
          onClick={() => query.refetch()}
          className="mt-3 rounded bg-primary px-3 py-1 text-sm text-on-primary"
        >
          Retry
        </button>
      </div>
    );
  }
  const data = query.data as T;
  if (isEmpty?.(data)) {
    return (
      <div role="status" className="rounded border border-border bg-surface p-4 text-muted">
        {empty ?? `No ${label} to show.`}
      </div>
    );
  }
  return <>{children(data)}</>;
}

/** A region that may be missing while the rest of the page works (for example the AI brief). */
export function Partial({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div role="status" className="rounded border border-dashed border-border p-3 text-sm text-muted">
      <span className="font-semibold">{title}: </span>
      {children}
    </div>
  );
}
