import type { HTMLAttributes } from "react";

import { cn } from "../../lib/utils";

/** A placeholder block shaped like the content it stands for (decorative: aria-hidden). */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-border", className)} {...props} />;
}
