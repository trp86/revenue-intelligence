// Opportunity Detail: why does it exist? Three distinct blocks: Measured fact, Estimate and
// AI suggestion, told apart by heading text, an icon and a token colour (spec 07 section 6).
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { AiBriefBlock } from "../components/AiBrief";
import { AsyncBoundary } from "../components/AsyncBoundary";
import { ConfidenceBadge, customerLabel, PriorityBadge, TYPE_LABEL } from "../components/labels";
import { useCrumbTitle } from "../components/layout/crumbs";
import { Metric } from "../components/Metric";

const FACT_LABELS: Record<string, string> = {
  days_since_last_order: "Days since the last order",
  median_interval_days: "Usual days between orders",
  n_orders: "Orders up to the as-of date",
  last_order_date: "Last order date",
  lookback_net_sales: "Net sales before going quiet",
  prior_net_sales: "Net sales, same months last year",
  current_net_sales: "Net sales, latest months",
  prior_orders: "Orders, same months last year",
  decline_pct: "Decline on last year",
  n_peers: "Peers in the group",
  n_buying_peers: "Peers buying the category",
  peer_penetration: "Share of peers buying it",
  peer_median_net_sales: "Median net sales of buying peers",
  support: "Customers who bought both",
  confidence: "Buyers of A who also bought B",
  lift: "Lift",
  median_b_net_sales: "Median net sales in B",
};

export function Detail() {
  const { id = "" } = useParams();
  const query = useQuery({ queryKey: ["opportunity", id], queryFn: () => api.opportunity(id) });
  useCrumbTitle(query.data ? `${TYPE_LABEL[query.data.type]}: ${customerLabel(query.data.customer)}` : null);
  return (
    <section aria-labelledby="detail-title" className="space-y-4">
      <Link to="/opportunities" className="text-sm text-primary underline">← All opportunities</Link>
      <AsyncBoundary query={query} label="this opportunity">
        {(o) => (
          <>
            <header className="space-y-1">
              <h1 id="detail-title" className="text-2xl font-semibold">
                {TYPE_LABEL[o.type]}: {customerLabel(o.customer)}
              </h1>
              <p className="flex flex-wrap gap-4 text-sm">
                <span>Rank #{o.rank}</span>
                {o.category && <span>Category: {o.category}</span>}
                {o.branch && <span>Branch: {o.branch}</span>}
                <span>Priority: <PriorityBadge level={o.priority} /></span>
                <span>Confidence: <ConfidenceBadge level={o.confidence} /></span>
                <span>Score <Metric metric={o.score} label="score" /></span>
                <span>As of {o.as_of_date}</span>
              </p>
              {o.customer.f_multi_identity && (
                <p role="note" className="text-sm text-warn">
                  ⚠ This customer code may stand for more than one customer (multiple spellings).
                </p>
              )}
            </header>

            <div className="grid gap-4 md:grid-cols-2">
              <section aria-labelledby="measured-title"
                className="rounded-lg border-l-4 border-measured bg-measured-bg p-4">
                <h2 id="measured-title" className="mb-2 font-semibold text-measured">
                  <span aria-hidden="true">✔ </span>Measured fact
                </h2>
                <dl className="space-y-1 text-sm">
                  {o.measured.map((f) => (
                    <div key={f.fact} className="flex justify-between gap-4">
                      <dt>{FACT_LABELS[f.fact] ?? f.fact}</dt>
                      <dd className="font-semibold">
                        <Metric metric={{ value: f.value, unit: f.unit,
                          definition_id: f.definition_id }} label={FACT_LABELS[f.fact] ?? f.fact} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>

              <section aria-labelledby="estimate-title"
                className="rounded-lg border-l-4 border-estimate bg-estimate-bg p-4">
                <h2 id="estimate-title" className="mb-2 font-semibold text-estimate">
                  <span aria-hidden="true">≈ </span>Estimate
                </h2>
                <p className="text-sm">
                  Value range:{" "}
                  <Metric metric={o.estimate.value_low} label="value low" />
                  {" to "}
                  <Metric metric={o.estimate.value_high} label="value high" />{" "}
                  (level: {o.estimate.value_level})
                </p>
                {o.estimate.method && (
                  <p className="mt-2 text-xs text-muted">{o.estimate.method}</p>
                )}
              </section>
            </div>

            <section aria-labelledby="ai-title" className="rounded-lg border-l-4 border-ai bg-ai-bg p-4">
              <h2 id="ai-title" className="mb-2 font-semibold text-ai">
                <span aria-hidden="true">✦ </span>AI suggestion
              </h2>
              <AiBriefBlock oppId={o.opp_id} />
            </section>

            {(o.data_quality_notes.length > 0 || o.reason_codes.length > 0) && (
              <section aria-labelledby="notes-title" className="rounded-lg border border-border bg-surface p-4 text-sm">
                <h2 id="notes-title" className="mb-2 font-semibold">Why it was flagged</h2>
                <ul className="list-disc pl-5">
                  {o.reason_codes.map((r) => <li key={r}>{r.replaceAll("_", " ")}</li>)}
                  {o.data_quality_notes.map((n) => <li key={n} className="text-warn">⚠ {n}</li>)}
                </ul>
              </section>
            )}
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}
