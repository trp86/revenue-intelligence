// The preview of the selected row (story #149): what happened, why it matters, and a link to
// the full Detail page. It loads the opportunity by id, so a shared link restores it even when
// the row is on another page.
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, MousePointerClick } from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import { summaryFor } from "../../summaries";
import { ConfidenceBadge, customerLabel, PriorityBadge, TypeBadge } from "../labels";
import { Metric } from "../Metric";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Skeleton } from "../ui/skeleton";

export function OpportunityPreview({ id }: { id: string | null }) {
  const detail = useQuery({
    queryKey: ["opportunity", id],
    queryFn: () => api.opportunity(id!),
    enabled: id !== null,
  });
  if (id === null) {
    return (
      <Card className="flex flex-col items-center gap-2 p-6 text-center text-sm text-muted">
        <MousePointerClick className="h-6 w-6" aria-hidden="true" />
        Select an opportunity to preview what happened and why it matters.
      </Card>
    );
  }
  if (detail.isPending) {
    return (
      <Card role="status" aria-busy="true" className="space-y-3 p-6">
        <span className="sr-only">Loading the preview…</span>
        <Skeleton className="h-5 w-32" /><Skeleton className="h-6 w-2/3" /><Skeleton className="h-16 w-full" />
        <Skeleton className="h-24 w-full" />
      </Card>
    );
  }
  if (detail.isError) {
    return (
      <Card role="alert" className="p-6 text-sm text-danger">
        This opportunity could not be loaded. Select another row or try again.
      </Card>
    );
  }
  const item = detail.data;
  return (
    <Card role="region" aria-label="Preview">
      <CardHeader>
        <TypeBadge type={item.type} />
        <CardTitle className="mt-2 break-words text-lg">{customerLabel(item.customer)}</CardTitle>
        <p className="text-sm text-muted">
          Rank #{item.rank}
          {item.category ? ` · ${item.category}` : ""}
          {item.branch ? ` · ${item.branch}` : ""}
        </p>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <section aria-labelledby="preview-what">
          <h3 id="preview-what" className="mb-1 text-xs font-semibold uppercase tracking-wide text-measured">
            What happened
          </h3>
          <p className="text-text">{summaryFor(item.type, item.measured, item.category)}</p>
        </section>
        <section aria-labelledby="preview-why">
          <h3 id="preview-why" className="mb-2 text-xs font-semibold uppercase tracking-wide text-opportunity">
            Why it matters
          </h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            <dt className="text-muted">Value (estimate)</dt>
            <dd className="text-right">
              <Metric metric={item.value_low} label="value low" hideUnit />
              {" – "}
              <Metric metric={item.value_high} label="value high" hideUnit />
            </dd>
            <dt className="text-muted">Priority</dt>
            <dd className="text-right"><PriorityBadge level={item.priority} /></dd>
            <dt className="text-muted">Confidence</dt>
            <dd className="text-right"><ConfidenceBadge level={item.confidence} /></dd>
            <dt className="text-muted">Score</dt>
            <dd className="text-right"><Metric metric={item.score} label="score" /></dd>
          </dl>
        </section>
        <Button asChild className="w-full">
          <Link to={`/opportunities/${item.opp_id}`}>
            Open details <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
