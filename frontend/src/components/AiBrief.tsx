// The content of the AI suggestion block (spec 05 section 9, stories #138 and #150): the brief
// with its provenance, or "Get suggestions" (plain wording since #183, short dialogs since #185).
// Getting asks for confirmation first (it calls Gemini and counts toward the daily limit) and reports the result in a toast. When AI is off or
// failing the block says so; the measured evidence on the page is unaffected.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ListChecks, RefreshCw, ShieldAlert, Sparkles } from "lucide-react";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { BriefResponse } from "../api/types";
import { ConfirmDialog } from "./feedback/ConfirmDialog";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Skeleton } from "./ui/skeleton";
import { toast } from "./ui/toaster";

function Brief({ data, onRegenerate, busy }: { data: BriefResponse; onRegenerate: () => void; busy: boolean }) {
  const { brief } = data;
  return (
    <div className="space-y-4 text-sm">
      <div>
        <p className="font-heading text-lg font-semibold text-text">{brief.headline}</p>
        <p className="mt-1 text-text">{brief.explanation}</p>
      </div>
      <div className="rounded-md border border-ai bg-ai-bg p-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-ai">What to do</p>
        <p className="mt-1 text-text">{brief.recommendation}</p>
      </div>
      {brief.actions.length > 0 && (
        <div>
          <p className="flex items-center gap-1 font-semibold text-text">
            <ListChecks className="h-4 w-4 text-ai" aria-hidden="true" /> Suggested actions
          </p>
          <ul className="mt-1 space-y-1">
            {brief.actions.map((a) => (
              <li key={a.text} className="flex flex-wrap items-center gap-2">
                <span>{a.text}</span>
                <Badge tone="neutral">{a.suggested_owner_role}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
      {brief.risks.length > 0 && (
        <div>
          <p className="flex items-center gap-1 font-semibold text-text">
            <ShieldAlert className="h-4 w-4 text-danger" aria-hidden="true" /> Risks
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5">{brief.risks.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      {/* story #189: no provenance on screen (it is still stored and returned by the API, spec 05 section 7) */}
      <div className="border-t border-border pt-3">
        {/* story #181: a fresh suggestion; the old one stays in the history */}
        <Button variant="outline" size="sm" onClick={onRegenerate} disabled={busy} aria-busy={busy}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          {busy ? "Refreshing…" : "Refresh suggestions"}
        </Button>
      </div>
    </div>
  );
}

export function AiBriefBlock({ oppId }: { oppId: string }) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [confirmingRegenerate, setConfirmingRegenerate] = useState(false);
  const query = useQuery({
    queryKey: ["brief", oppId],
    queryFn: () => api.brief(oppId),
    retry: false,
  });
  const generate = useMutation({
    mutationFn: (regenerate: boolean) => api.generateBrief(oppId, regenerate),
    onSuccess: (data, regenerate) => {
      client.setQueryData(["brief", oppId], data);
      toast.success(regenerate ? "New suggestions ready"
        : "Suggestions ready");
    },
    onError: (error, regenerate) => {
      const disabled = error instanceof ApiError && error.code === "ai_disabled";
      // on a failed regenerate the previous brief stays on screen (story #181)
      toast.error(disabled ? "Suggestions are turned off"
        : regenerate ? "New suggestions could not be created; the current ones are kept"
        : "Suggestions could not be created");
    },
  });

  if (query.isPending) {
    return (
      <div role="status" aria-live="polite" aria-busy="true" className="space-y-2">
        <span className="sr-only">Loading the suggestions…</span>
        <Skeleton className="h-5 w-2/3" /><Skeleton className="h-4 w-full" /><Skeleton className="h-16 w-full" />
      </div>
    );
  }
  if (query.data) {
    return (
      <>
        <Brief data={query.data} busy={generate.isPending} onRegenerate={() => setConfirmingRegenerate(true)} />
        <ConfirmDialog
          open={confirmingRegenerate}
          onOpenChange={setConfirmingRegenerate}
          title="Refresh suggestions?"
          description="We'll replace these suggestions with new ones. The current ones are kept in the history."
          confirmLabel="Refresh"
          onConfirm={() => generate.mutate(true)}
        />
      </>
    );
  }

  const missing = query.error instanceof ApiError && query.error.code === "no_brief";
  const failed = generate.error instanceof ApiError ? generate.error : null;
  return (
    <div className="space-y-3">
      <p role="status" className="text-sm text-muted">
        {missing
          ? "No suggestions yet for this customer."
          : `Suggestions are not available right now (${query.error instanceof ApiError ? query.error.message : "error"}). ` +
            "The measured facts and the estimate are complete."}
      </p>
      {failed && (
        <p role="alert" className="flex items-start gap-2 rounded-md border border-danger bg-danger-bg p-3 text-sm text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {failed.code === "ai_disabled" ? "Suggestions are turned off." : failed.message}
        </p>
      )}
      <Button
        onClick={() => setConfirming(true)}
        disabled={generate.isPending}
        aria-busy={generate.isPending}
      >
        <Sparkles className="h-4 w-4" aria-hidden="true" />
        {generate.isPending ? "Getting suggestions…" : "Get suggestions"}
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Get suggestions?"
        description="We'll suggest next steps based on the facts on this page. Customer names are never shared."
        confirmLabel="Get suggestions"
        onConfirm={() => generate.mutate(false)}
      />
    </div>
  );
}
