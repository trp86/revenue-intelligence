// Loading, empty, error and partial states for every data region (spec 07 section 5; story #146
// adds skeletons shaped like the content).
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { EmptyState } from "./feedback/EmptyState";
import { ErrorState } from "./feedback/ErrorState";
import { Skeleton } from "./ui/skeleton";

export type SkeletonKind = "lines" | "cards" | "table" | "detail";

interface Props<T> {
  query: { isPending: boolean; isError: boolean; error: unknown; data: T | undefined;
    refetch: () => unknown };
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  emptyAction?: ReactNode;
  emptyTitle?: string;
  label: string;
  skeleton?: SkeletonKind;
  children: (data: T) => ReactNode;
}

export function SkeletonBlock({ kind = "lines" }: { kind?: SkeletonKind }) {
  if (kind === "cards") {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" data-skeleton="cards">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28 rounded-lg" />)}
      </div>
    );
  }
  if (kind === "table") {
    return (
      <div className="space-y-2" data-skeleton="table">
        <Skeleton className="h-10" />
        {[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-11" />)}
      </div>
    );
  }
  if (kind === "detail") {
    return (
      <div className="space-y-4" data-skeleton="detail">
        <Skeleton className="h-28 rounded-lg" />
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48 rounded-lg" />
          <Skeleton className="h-48 rounded-lg" />
        </div>
        <Skeleton className="h-40 rounded-lg" />
      </div>
    );
  }
  return (
    <div className="space-y-2" data-skeleton="lines">
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  );
}

export function AsyncBoundary<T>({
  query,
  isEmpty,
  empty,
  emptyAction,
  emptyTitle = "Nothing to show",
  label,
  skeleton,
  children,
}: Props<T>) {
  if (query.isPending) {
    return (
      <div role="status" aria-live="polite" aria-busy="true">
        <span className="sr-only">Loading {label}…</span>
        <SkeletonBlock kind={skeleton} />
      </div>
    );
  }
  if (query.isError) {
    const message =
      query.error instanceof ApiError ? query.error.message : "Something went wrong.";
    return <ErrorState title={`Could not load ${label}`} message={message} onRetry={() => query.refetch()} />;
  }
  const data = query.data as T;
  if (isEmpty?.(data)) {
    return <EmptyState title={emptyTitle} reason={empty ?? `No ${label} to show.`} action={emptyAction} />;
  }
  return <>{children(data)}</>;
}

/** A region that may be missing while the rest of the page works (for example the AI brief). */
export function Partial({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div role="status" className="rounded-lg border border-dashed border-border p-3 text-sm text-muted">
      <span className="font-semibold">{title}: </span>
      {children}
    </div>
  );
}
