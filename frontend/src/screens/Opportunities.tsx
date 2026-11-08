// Opportunity Explorer: the main working screen (spec 07 sections 3 and 8, story #149). Type
// tabs, filters and removable chips, a ranked table, and a preview of the selected row. Filters,
// sort, page and the selected row are held in the URL, so back, forward and a shared link restore
// them.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Eye } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Level, OpportunityFilters, OppType } from "../api/types";
import { AsyncBoundary } from "../components/AsyncBoundary";
import { BranchSearch, FilterSelect } from "../components/explorer/FilterBar";
import { FilterChips, type Chip } from "../components/explorer/FilterChips";
import { OpportunityPreview } from "../components/explorer/OpportunityPreview";
import { TypeTabs } from "../components/explorer/TypeTabs";
import {
  ConfidenceBadge,
  customerLabel,
  PriorityBadge,
  TYPE_LABEL,
  TypeBadge,
} from "../components/labels";
import { PageHeader } from "../components/layout/PageHeader";
import { DefinitionButton, Metric } from "../components/Metric";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { formatKpi, formatValue } from "../format";
import { cn } from "../lib/utils";
import { useMoneyUnit } from "../money";

const LEVELS: Level[] = ["High", "Medium", "Low"];
const SORTS: { value: NonNullable<OpportunityFilters["sort"]>; label: string }[] = [
  { value: "rank", label: "Rank" },
  { value: "score", label: "Score" },
  { value: "value_high", label: "Value (high estimate)" },
];
const PAGE_SIZE = 25;
const FILTER_KEYS = ["type", "priority", "confidence", "branch"] as const;

const MILLION = 1_000_000;

/** The value range of a row, compact from a million (9.17M – 27.52M), full numbers in its title (story #187). */
export function ValueRange({ low, high }: { low: number | null; high: number | null }) {
  const full = `${formatValue(low, "net sales")} – ${formatValue(high, "net sales")}`;
  const wide = Math.max(Math.abs(low ?? 0), Math.abs(high ?? 0)) >= MILLION;
  if (!wide || low === null || high === null) return <span className="tabular-nums">{full}</span>;
  return (
    <span className="tabular-nums">
      <span aria-hidden="true" title={full}>{`${formatKpi(low)} – ${formatKpi(high)}`}</span>
      <span className="sr-only">{full}</span>
    </span>
  );
}

export function Opportunities() {
  const money = useMoneyUnit();
  const [params, setParams] = useSearchParams();
  const sort = (params.get("sort") as OpportunityFilters["sort"]) || "rank";
  const filters: OpportunityFilters = {
    type: (params.get("type") as OppType) || undefined,
    priority: (params.get("priority") as Level) || undefined,
    confidence: (params.get("confidence") as Level) || undefined,
    branch: params.get("branch") || undefined,
    sort,
    page: Number(params.get("page") ?? "1") || 1,
    page_size: PAGE_SIZE,
  };
  const selectedId = params.get("selected");
  const query = useQuery({
    queryKey: ["opportunities", filters],
    queryFn: () => api.opportunities(filters),
    placeholderData: keepPreviousData,
  });

  function update(changes: Record<string, string | undefined>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!("page" in changes)) next.delete("page");
    if (!("selected" in changes) && !("page" in changes)) next.delete("selected");
    setParams(next);
  }

  const chips: Chip[] = [];
  if (filters.type) chips.push({ key: "type", label: `Type: ${TYPE_LABEL[filters.type]}` });
  if (filters.priority) chips.push({ key: "priority", label: `Priority: ${filters.priority}` });
  if (filters.confidence) chips.push({ key: "confidence", label: `Confidence: ${filters.confidence}` });
  if (filters.branch) chips.push({ key: "branch", label: `Branch: ${filters.branch}` });
  const clearAll = () => update(Object.fromEntries(FILTER_KEYS.map((k) => [k, undefined])));

  const sortedBy = (column: OpportunityFilters["sort"]) =>
    sort === column ? (column === "rank" ? "ascending" : "descending") : undefined;

  return (
    <section aria-labelledby="page-title" className="space-y-4">
      <PageHeader
        title={<span id="page-title">Opportunity Explorer</span>}
        subtitle="Filter, scan and preview the ranked opportunities. Select a row to see what happened."
      />
      <Card className="space-y-4 p-4">
        <TypeTabs value={filters.type} onChange={(type) => update({ type })} />
        <form aria-label="Filters" onSubmit={(e) => e.preventDefault()}
          className="flex flex-wrap items-end gap-3">
          <FilterSelect label="Priority" value={filters.priority ?? ""}
            options={LEVELS.map((l) => ({ value: l, label: l }))}
            onChange={(v) => update({ priority: v || undefined })} />
          <FilterSelect label="Confidence" value={filters.confidence ?? ""}
            options={LEVELS.map((l) => ({ value: l, label: l }))}
            onChange={(v) => update({ confidence: v || undefined })} />
          <BranchSearch value={filters.branch ?? ""} onChange={(v) => update({ branch: v || undefined })} />
          <FilterSelect label="Sort by" value={sort} options={SORTS} allLabel={null}
            onChange={(v) => update({ sort: v === "rank" ? undefined : v })} />
        </form>
        <FilterChips chips={chips} onRemove={(key) => update({ [key]: undefined })} onClear={clearAll} />
      </Card>

      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_20rem]">
        <AsyncBoundary
          query={query}
          label="opportunities"
          skeleton="table"
          isEmpty={(d) => d.total === 0}
          emptyTitle="No opportunities match"
          empty="No opportunities match these filters. Clear a filter to see more."
          emptyAction={chips.length > 0 ? <Button variant="outline" onClick={clearAll}>Clear filters</Button> : undefined}
        >
          {(data) => {
            const pages = Math.max(1, Math.ceil(data.total / data.page_size));
            return (
              <Card className="min-w-0">
                <p className="px-4 pt-4 text-sm text-muted" aria-live="polite">
                  <span className="font-semibold text-text">{data.total.toLocaleString("en-US")} opportunities</span>
                  {` · page ${data.page} of ${pages}`}
                </p>
                <div className="mt-2">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead scope="col" aria-sort={sortedBy("rank")}>Rank</TableHead>
                        <TableHead scope="col">Type</TableHead>
                        <TableHead scope="col">Customer and category</TableHead>
                        <TableHead scope="col">Priority</TableHead>
                        <TableHead scope="col" className="hidden xl:table-cell">Confidence</TableHead>
                        <TableHead scope="col" aria-sort={sortedBy("score")} className="text-right">
                          <span className="inline-flex items-center gap-1">
                            Score <DefinitionButton definitionId="opp_score" label="score" />
                          </span>
                        </TableHead>
                        <TableHead scope="col" aria-sort={sortedBy("value_high")} className="text-right">
                          <span className="inline-flex items-center gap-1">
                            Value (estimate, {money})
                            <DefinitionButton definitionId="opp_value_high" label="value (estimate)" unit="net sales" />
                          </span>
                        </TableHead>
                        <TableHead scope="col"><span className="sr-only">Preview</span></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.items.map((item) => {
                        const selected = item.opp_id === selectedId;
                        return (
                          <TableRow key={item.opp_id} aria-current={selected ? "true" : undefined}
                            onClick={() => update({ selected: item.opp_id, page: params.get("page") ?? undefined })}
                            className={cn("cursor-pointer", selected && "bg-opportunity-bg hover:bg-opportunity-bg")}>
                            <TableCell className="tabular text-muted">{item.rank}</TableCell>
                            <TableCell><TypeBadge type={item.type} short /></TableCell>
                            <TableCell className="max-w-[14rem]">
                              <Link to={`/opportunities/${item.opp_id}`} title={customerLabel(item.customer)}
                                onClick={(e) => e.stopPropagation()}
                                className="block truncate font-medium text-primary hover:underline">
                                {customerLabel(item.customer)}
                              </Link>
                              <span className="block truncate text-xs text-muted" title={item.category ?? undefined}>
                                {item.category ?? "Whole customer"}
                              </span>
                            </TableCell>
                            <TableCell><PriorityBadge level={item.priority} /></TableCell>
                            <TableCell className="hidden xl:table-cell"><ConfidenceBadge level={item.confidence} /></TableCell>
                            <TableCell className="text-right">
                              <Metric metric={item.score} label="score" hideDefinition />
                            </TableCell>
                            <TableCell className="whitespace-nowrap text-right">
                              <ValueRange low={item.value_low.value} high={item.value_high.value} />
                            </TableCell>
                            <TableCell>
                              <Button variant="ghost" size="icon" aria-pressed={selected}
                                aria-label={`Preview ${customerLabel(item.customer)}`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  update({ selected: item.opp_id, page: params.get("page") ?? undefined });
                                }}>
                                <Eye className="h-4 w-4" aria-hidden="true" />
                              </Button>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
                <nav aria-label="Pages" className="flex items-center justify-end gap-2 p-3">
                  <Button variant="outline" size="sm" disabled={data.page <= 1}
                    onClick={() => update({ page: String(data.page - 1) })}>
                    <ChevronLeft className="h-4 w-4" aria-hidden="true" /> Previous
                  </Button>
                  <Button variant="outline" size="sm" disabled={data.page >= pages}
                    onClick={() => update({ page: String(data.page + 1) })}>
                    Next <ChevronRight className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </nav>
              </Card>
            );
          }}
        </AsyncBoundary>
        <div className="2xl:sticky 2xl:top-20 2xl:self-start">
          <OpportunityPreview id={selectedId} />
        </div>
      </div>
    </section>
  );
}
