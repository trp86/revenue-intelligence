// The AI suggestion block (spec 05 section 9, story #138): the brief, labelled as AI and with
// its provenance, or a Generate button. When AI is off or failing the block says so and the
// rest of the page, the measured evidence, still works.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "../api/client";
import type { BriefResponse } from "../api/types";
import { Partial } from "./AsyncBoundary";

function Brief({ data }: { data: BriefResponse }) {
  const { brief, provenance } = data;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-base font-semibold">{brief.headline}</p>
      <p>{brief.explanation}</p>
      <p><span className="font-semibold">Recommendation: </span>{brief.recommendation}</p>
      {brief.actions.length > 0 && (
        <div>
          <p className="font-semibold">Suggested actions</p>
          <ul className="list-disc pl-5">
            {brief.actions.map((a) => (
              <li key={a.text}>{a.text} <span className="text-muted">({a.suggested_owner_role})</span></li>
            ))}
          </ul>
        </div>
      )}
      {brief.risks.length > 0 && (
        <div>
          <p className="font-semibold">Risks</p>
          <ul className="list-disc pl-5">{brief.risks.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      <p className="text-xs text-muted">
        AI suggestion, not a measured fact Â· confidence {brief.confidence_label} Â· model{" "}
        {provenance.model} Â· prompt {provenance.prompt_version} Â· generated{" "}
        {provenance.generated_at.replace("T", " ").slice(0, 16)} Â· {provenance.review_status}
      </p>
    </div>
  );
}

export function AiBriefBlock({ oppId }: { oppId: string }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["brief", oppId],
    queryFn: () => api.brief(oppId),
    retry: false,
  });
  const generate = useMutation({
    mutationFn: () => api.generateBrief(oppId),
    onSuccess: (data) => client.setQueryData(["brief", oppId], data),
  });

  if (query.isPending) {
    return <p role="status" aria-live="polite" className="text-sm text-muted">Loading the AI briefâ€¦</p>;
  }
  if (query.data) return <Brief data={query.data} />;

  const missing = query.error instanceof ApiError && query.error.code === "no_brief";
  const failed = generate.error instanceof ApiError ? generate.error : null;
  return (
    <div className="space-y-2">
      {missing ? (
        <Partial title="AI brief">none yet for this opportunity.</Partial>
      ) : (
        <Partial title="AI brief">
          not available ({query.error instanceof ApiError ? query.error.message : "error"}). The
          measured facts and the estimate are complete.
        </Partial>
      )}
      {failed && (
        <p role="alert" className="text-sm text-danger">
          âš  {failed.code === "ai_disabled" ? "AI briefs are turned off." : failed.message}
        </p>
      )}
      <button
        type="button"
        onClick={() => generate.mutate()}
        disabled={generate.isPending}
        aria-busy={generate.isPending}
        className="rounded bg-primary px-3 py-1 text-sm text-on-primary disabled:opacity-60"
      >
        {generate.isPending ? "Generatingâ€¦" : "Generate brief"}
      </button>
    </div>
  );
}
