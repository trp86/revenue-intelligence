// Toasts (story #146; own implementation since story #150, because sonner renders each toast as
// an <li role="status">, which axe rejects). One polite live region, toasts close after 4 s or by
// their close button, and they never take focus. Usage: toast.success("..."), toast.error("...").
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { useSyncExternalStore } from "react";

import { cn } from "../../lib/utils";

type Kind = "success" | "error";

interface Item {
  id: number;
  kind: Kind;
  message: string;
}

const DURATION_MS = 4000;
let items: Item[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function dismiss(id: number) {
  items = items.filter((item) => item.id !== id);
  emit();
}

function show(kind: Kind, message: string): number {
  const id = nextId++;
  items = [...items, { id, kind, message }];
  emit();
  setTimeout(() => dismiss(id), DURATION_MS);
  return id;
}

export const toast = {
  success: (message: string) => show("success", message),
  error: (message: string) => show("error", message),
  dismiss,
};

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function Toaster() {
  const current = useSyncExternalStore(subscribe, () => items, () => items);
  return (
    <div
      role="region"
      aria-label="Notifications"
      className="pointer-events-none fixed bottom-4 right-4 z-toast flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2"
    >
      <div role="status" aria-live="polite" className="flex flex-col gap-2">
        {current.map((item) => {
          const Icon = item.kind === "success" ? CheckCircle2 : AlertTriangle;
          return (
            <div
              key={item.id}
              className={cn(
                "pointer-events-auto flex items-start gap-3 rounded-lg border border-border bg-surface p-3 text-sm text-text shadow-md",
              )}
            >
              <Icon
                className={cn("mt-0.5 h-5 w-5 shrink-0", item.kind === "success" ? "text-success" : "text-danger")}
                aria-hidden="true"
              />
              <p className="flex-1">{item.message}</p>
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={() => dismiss(item.id)}
                className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-md text-muted hover:bg-surface-muted"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
