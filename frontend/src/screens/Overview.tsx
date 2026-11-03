// Overview: where do I focus this week? (spec 07 section 3, story #136)
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Overview as OverviewData } from "../api/types";
import { AsyncBoundary } from "../components/AsyncBoundary";
import { customerLabel, PriorityBadge, TYPE_LABEL } from "../components/labels";
import { Metric } from "../components/Metric";

export function Overview() {
  const query = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  return (
    <section aria-labelledby="overview-title" className="space-y-6">
      <h1 id="overview-title" className="text-2xl font-semibold">Overview</h1>
      <AsyncBoundary
        query={query}
        label="the overview"
        isEmpty={(d: OverviewData) => d.kpis.opportunities.value === 0}
        empty="No opportunities for this as-of date. Run `revint opportunities build`."
      >
        {(data) => (
          <>
            <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
              {[
                ["Opportunities", data.kpis.opportunities],
                ["Customers", data.kpis.customers],
                ["Value, low estimate", data.kpis.value_low],
                ["Value, high estimate", data.kpis.value_high],
              ].map(([label, metric]) => (
                <div key={label as string} className="rounded-lg border border-border bg-surface p-4">
                  <dt className="text-sm text-muted">{label as string}</dt>
                  <dd className="mt-1 text-xl font-semibold">
                    <Metric metric={metric as OverviewData["kpis"]["value_low"]}
                      label={label as string} />
                  </dd>
                </div>
              ))}
            </dl>

            <div className="rounded-lg border border-border bg-surface p-4">
              <h2 className="mb-3 text-lg font-semibold">Opportunities by type</h2>
              <table className="w-full text-left text-sm">
                <thead className="text-muted">
                  <tr>
                    <th scope="col" className="py-1">Type</th>
                    <th scope="col">Count</th>
                    <th scope="col">High</th>
                    <th scope="col">Medium</th>
                    <th scope="col">Low</th>
                    <th scope="col">Value, high estimate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_type.map((row) => (
                    <tr key={row.type} className="border-t border-border">
                      <th scope="row" className="py-2 font-normal">
                        <Link className="text-primary underline" to={`/opportunities?type=${row.type}`}>
                          {TYPE_LABEL[row.type]}
                        </Link>
                      </th>
                      <td><Metric metric={row.count} label={`${row.type} count`} /></td>
                      <td>{row.by_priority.High}</td>
                      <td>{row.by_priority.Medium}</td>
                      <td>{row.by_priority.Low}</td>
                      <td><Metric metric={row.value_high} label={`${row.type} value`} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="rounded-lg border border-border bg-surface p-4">
              <h2 className="mb-3 text-lg font-semibold">Top {data.top.length} opportunities</h2>
              <ol className="divide-y divide-border">
                {data.top.map((item) => (
                  <li key={item.opp_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <Link className="text-primary underline" to={`/opportunities/${item.opp_id}`}>
                      #{item.rank} {TYPE_LABEL[item.type]}: {customerLabel(item.customer)}
                      {item.category ? ` — ${item.category}` : ""}
                    </Link>
                    <span className="flex items-center gap-4 text-sm">
                      <PriorityBadge level={item.priority} />
                      <span>Score <Metric metric={item.score} label="score" /></span>
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}
