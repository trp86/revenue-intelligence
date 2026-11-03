// Opportunities: which to act on? A ranked table with filters and sort in the URL (spec 07
// sections 3 and 8, story #136).
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Level, OpportunityFilters, OppType } from "../api/types";
import { AsyncBoundary } from "../components/AsyncBoundary";
import { ConfidenceBadge, customerLabel, PriorityBadge, TYPE_LABEL } from "../components/labels";
import { Metric } from "../components/Metric";

const LEVELS: Level[] = ["High", "Medium", "Low"];
const TYPES = Object.keys(TYPE_LABEL) as OppType[];
const SORTS = { rank: "Rank", score: "Score", value_high: "Value (high estimate)" };
const PAGE_SIZE = 25;

export function Opportunities() {
  const [params, setParams] = useSearchParams();
  const filters: OpportunityFilters = {
    type: (params.get("type") as OppType) || undefined,
    priority: (params.get("priority") as Level) || undefined,
    confidence: (params.get("confidence") as Level) || undefined,
    branch: params.get("branch") || undefined,
    sort: (params.get("sort") as OpportunityFilters["sort"]) || "rank",
    page: Number(params.get("page") ?? "1") || 1,
    page_size: PAGE_SIZE,
  };
  const query = useQuery({
    queryKey: ["opportunities", filters],
    queryFn: () => api.opportunities(filters),
    placeholderData: keepPreviousData,
  });

  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  }

  const select = (key: string, label: string, options: [string, string][]) => (
    <label className="flex flex-col text-sm">
      <span className="text-muted">{label}</span>
      <select
        value={params.get(key) ?? ""}
        onChange={(e) => update(key, e.target.value)}
        className="rounded border border-border bg-surface px-2 py-1"
      >
        {key !== "sort" && <option value="">All</option>}
        {options.map(([value, text]) => (
          <option key={value} value={value}>{text}</option>
        ))}
      </select>
    </label>
  );

  return (
    <section aria-labelledby="opps-title" className="space-y-4">
      <h1 id="opps-title" className="text-2xl font-semibold">Opportunities</h1>
      <form className="flex flex-wrap items-end gap-4" aria-label="Filters"
        onSubmit={(e) => e.preventDefault()}>
        {select("type", "Type", TYPES.map((t) => [t, TYPE_LABEL[t]]))}
        {select("priority", "Priority", LEVELS.map((l) => [l, l]))}
        {select("confidence", "Confidence", LEVELS.map((l) => [l, l]))}
        <label className="flex flex-col text-sm">
          <span className="text-muted">Branch</span>
          <input
            defaultValue={params.get("branch") ?? ""}
            onBlur={(e) => update("branch", e.target.value.trim())}
            onKeyDown={(e) => e.key === "Enter" && update("branch", e.currentTarget.value.trim())}
            className="rounded border border-border bg-surface px-2 py-1"
            placeholder="e.g. Magway"
          />
        </label>
        {select("sort", "Sort by", Object.entries(SORTS))}
      </form>

      <AsyncBoundary
        query={query}
        label="opportunities"
        isEmpty={(d) => d.total === 0}
        empty="No opportunities match these filters. Clear a filter to see more."
      >
        {(data) => {
          const pages = Math.max(1, Math.ceil(data.total / data.page_size));
          return (
            <div className="rounded-lg border border-border bg-surface">
              <p className="px-4 pt-3 text-sm text-muted" aria-live="polite">
                {data.total.toLocaleString("en-US")} opportunities · page {data.page} of {pages}
              </p>
              <table className="mt-2 w-full text-left text-sm">
                <thead className="text-muted">
                  <tr>
                    <th scope="col" className="px-4 py-2">Rank</th>
                    <th scope="col">Type</th>
                    <th scope="col">Customer</th>
                    <th scope="col">Category</th>
                    <th scope="col">Priority</th>
                    <th scope="col">Confidence</th>
                    <th scope="col">Score</th>
                    <th scope="col">Value range (estimate)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.opp_id} className="border-t border-border">
                      <td className="px-4 py-2 tabular-nums">{item.rank}</td>
                      <td>{TYPE_LABEL[item.type]}</td>
                      <td>
                        <Link className="text-primary underline" to={`/opportunities/${item.opp_id}`}>
                          <span className="block max-w-[16rem] truncate" title={customerLabel(item.customer)}>
                            {customerLabel(item.customer)}
                          </span>
                        </Link>
                      </td>
                      <td>{item.category ?? "—"}</td>
                      <td><PriorityBadge level={item.priority} /></td>
                      <td><ConfidenceBadge level={item.confidence} /></td>
                      <td><Metric metric={item.score} label="score" /></td>
                      <td className="whitespace-nowrap">
                        <Metric metric={item.value_low} label="value low" />
                        {" – "}
                        <Metric metric={item.value_high} label="value high" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <nav aria-label="Pages" className="flex items-center justify-end gap-2 p-3">
                <button type="button" disabled={data.page <= 1}
                  onClick={() => update("page", String(data.page - 1))}
                  className="rounded border border-border px-3 py-1 disabled:opacity-50">
                  Previous
                </button>
                <button type="button" disabled={data.page >= pages}
                  onClick={() => update("page", String(data.page + 1))}
                  className="rounded border border-border px-3 py-1 disabled:opacity-50">
                  Next
                </button>
              </nav>
            </div>
          );
        }}
      </AsyncBoundary>
    </section>
  );
}
