import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "../../lib/utils";

/** A pill. Always give it text (and usually an icon): colour is never the only signal. */
export const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-surface-muted text-muted ring-1 ring-border",
        opportunity: "bg-opportunity-bg text-opportunity",
        measured: "bg-measured-bg text-measured",
        ai: "bg-ai-bg text-ai",
        warn: "bg-warn-bg text-warn",
        danger: "bg-danger-bg text-danger",
        success: "bg-success-bg text-success",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
