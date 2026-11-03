// Toasts (sonner): close after 4 s, announced politely, never take focus.
import { Toaster as Sonner } from "sonner";

export { toast } from "sonner";

export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      duration={4000}
      closeButton
      toastOptions={{
        classNames: {
          toast: "rounded-lg border border-border bg-surface text-text shadow-md font-sans",
          description: "text-muted",
          success: "text-success",
          error: "text-danger",
        },
      }}
    />
  );
}
