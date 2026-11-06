// The content of the AI suggestion block (spec 05 section 9, stories #138 and #150): the brief
// with its provenance, or "Generate brief". Generating asks for confirmation first (it calls
// Gemini and counts toward the daily limit) and reports the result in a toast. When AI is off or
// failing the block says so; the measured evidence on the page is unaffected.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ListChecks, ShieldAlert, Sparkles } from "lucide-react";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { BriefResponse } from "../api/types";
import { ConfirmDialog } from "./feedback/ConfirmDialog";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Skeleton } from "./ui/skeleton";
import { toast } from "./ui/toaster";

function Brief({ data }: { data: BriefResponse }) {
  const { brief, provenance } = data;
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
      <p className="border-t border-border pt-3 text-xs text-muted">
        AI suggestion, not a measured fact {"·"} confidence {brief.confidence_label} {"·"} model{" "}
        {provenance.model} {"·"} prompt {provenance.prompt_version} {"·"} generated{" "}
        {provenance.generated_at.replace("T", " ").slice(0, 16)} {"·"} {provenance.review_status}
      </p>
    </div>
  );
}

export function AiBriefBlock({ oppId }: { oppId: string }) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const query = useQuery({
    queryKey: ["brief", oppId],
    queryFn: () => api.brief(oppId),
    retry: false,
  });
  const generate = useMutation({
    mutationFn: () => api.generateBrief(oppId),
    onSuccess: (data) => {
      client.setQueryData(["brief", oppId], data);
      toast.success(data.provenance.cached ? "AI brief loaded from the cache" : "AI brief generated");
    },
    onError: (error) => {
      const disabled = error instanceof ApiError && error.code === "ai_disabled";
      toast.error(disabled ? "AI briefs are turned off" : "The AI brief could not be generated");
    },
  });

  if (query.isPending) {
    return (
      <div role="status" aria-live="polite" aria-busy="true" className="space-y-2">
        <span className="sr-only">Loading the AI brief…</span>
        <Skeleton className="h-5 w-2/3" /><Skeleton className="h-4 w-full" /><Skeleton className="h-16 w-full" />
      </div>
    );
  }
  if (query.data) return <Brief data={query.data} />;

  const missing = query.error instanceof ApiError && query.error.code === "no_brief";
  const failed = generate.error instanceof ApiError ? generate.error : null;
  return (
    <div className="space-y-3">
      <p role="status" className="text-sm text-muted">
        {missing
          ? "There is no AI brief for this opportunity yet."
          : `The AI brief is not available (${query.error instanceof ApiError ? query.error.message : "error"}). ` +
            "The measured facts and the estimate are complete."}
      </p>
      {failed && (
        <p role="alert" className="flex items-start gap-2 rounded-md border border-danger bg-danger-bg p-3 text-sm text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {failed.code === "ai_disabled" ? "AI briefs are turned off." : failed.message}
        </p>
      )}
      <Button
        onClick={() => setConfirming(true)}
        disabled={generate.isPending}
        aria-busy={generate.isPending}
      >
        <Sparkles className="h-4 w-4" aria-hidden="true" />
        {generate.isPending ? "Generating…" : "Generate brief"}
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Generate an AI brief?"
        description="This sends the measured facts of this opportunity (never customer names or codes) to Gemini and counts toward the daily limit. A brief that fails the checks is not shown."
        confirmLabel="Generate"
        onConfirm={() => generate.mutate()}
      />
    </div>
  );
}
