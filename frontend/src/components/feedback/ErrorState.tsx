import { AlertTriangle, RotateCw } from "lucide-react";

import { Button } from "../ui/button";

/** Something failed: the cause, and a way to retry (spec 07 section 5). */
export function ErrorState({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border border-danger bg-danger-bg p-4">
      <p className="flex items-center gap-2 font-semibold text-danger">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
        {title}
      </p>
      <p className="text-sm text-text">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-1">
          <RotateCw className="h-4 w-4" aria-hidden="true" />
          Retry
        </Button>
      )}
    </div>
  );
}
