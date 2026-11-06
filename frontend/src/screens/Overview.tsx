// Overview: where is the opportunity this week? (spec 07 section 3, story #148). KPI cards, two
// charts with table alternatives, and the top 10. Every chart, KPI and type opens the Explorer
// with the matching filter.
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Coins, Target, Users } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import type { Level, Overview as OverviewData, OppType } from "../api/types";
import { AsyncBoundary } from "../components/AsyncBoundary";
import { ChartCard } from "../components/display/ChartCard";
import { StatCard } from "../components/display/StatCard";
import { PageHeader } from "../components/layout/PageHeader";
import {
  customerLabel,
  PRIORITY_COLOR,
  PriorityBadge,
  TYPE_LABEL,
  TYPE_META,
  TYPE_SHORT,
  TypeBadge,
} from "../components/labels";
import { Metric } from "../components/Metric";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { formatCompact, formatValue } from "../format";
import { useMoneyUnit } from "../money";

const LEVELS: Level[] = ["High", "Medium", "Low"];

const SHORT = TYPE_SHORT;

function explorer(type?: OppType, priority?: Level) {
  const params = new URLSearchParams();
  if (type) params.set("type", type);
  if (priority) params.set("priority", priority);
  const query = params.toString();
  return `/opportunities${query ? `?${query}` : ""}`;
}

function ByTypeChart({ data }: { data: OverviewData }) {
  const navigate = useNavigate();
  const rows = [...data.by_type]
    .sort((a, b) => (b.count.value ?? 0) - (a.count.value ?? 0))
    .map((r) => ({ type: r.type, label: TYPE_LABEL[r.type], short: SHORT[r.type], ...r.by_priority,
      total: r.count.value }));
  const top = rows[0];
  const total = data.kpis.opportunities.value ?? 0;
  const high = rows.reduce((sum, r) => sum + r.High, 0);
  const summary = top
    ? `${top.label} has the most opportunities (${formatValue(top.total, "opportunities")} of ` +
      `${formatValue(total, "opportunities")}); ${formatValue(high, "opportunities")} ` +
      `${high === 1 ? "is" : "are"} High priority.`
    : "No opportunities.";
  return (
    <ChartCard
      title="Opportunities by type and priority"
      summary={summary}
      chart={
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--color-chart-grid)" />
            <XAxis dataKey="short" tick={{ fontSize: 12, fill: "var(--color-text-muted)" }}
              tickLine={false} axisLine={false} interval={0} />
            <YAxis tickFormatter={(v: number) => formatCompact(v)} width={48}
              tick={{ fontSize: 12, fill: "var(--color-text-muted)" }} tickLine={false} axisLine={false} />
            <Tooltip formatter={(v: number) => formatValue(v, "opportunities")}
              labelFormatter={(_l: string, p: { payload?: { label?: string } }[]) => p?.[0]?.payload?.label ?? _l}
              cursor={{ fill: "var(--color-surface-muted)" }} />
            <Legend iconType="square" wrapperStyle={{ fontSize: 12 }} />
            {LEVELS.map((level) => (
              <Bar key={level} dataKey={level} name={`${level} priority`} stackId="priority"
                fill={PRIORITY_COLOR[level]} cursor="pointer" isAnimationActive={false}
                onClick={(entry: { type?: OppType }) => navigate(explorer(entry.type, level))} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      }
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Type</TableHead>
              {LEVELS.map((l) => <TableHead key={l} scope="col" className="text-right">{l}</TableHead>)}
              <TableHead scope="col" className="text-right">Total</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.type}>
                <TableCell>
                  <Link className="font-medium text-primary hover:underline" to={explorer(r.type)}>{r.label}</Link>
                </TableCell>
                {LEVELS.map((l) => (
                  <TableCell key={l} className="tabular text-right">
                    <Link className="hover:underline" to={explorer(r.type, l)}
                      aria-label={`${r.label}, ${l} priority: ${formatValue(r[l], "opportunities")}`}>
                      {formatValue(r[l], "opportunities")}
                    </Link>
                  </TableCell>
                ))}
                <TableCell className="tabular text-right font-semibold">{formatValue(r.total, "opportunities")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    />
  );
}

function ValueChart({ data }: { data: OverviewData }) {
  const money = useMoneyUnit();
  const navigate = useNavigate();
  const rows = [...data.by_type]
    .sort((a, b) => (b.value_high.value ?? 0) - (a.value_high.value ?? 0))
    .map((r) => ({ type: r.type, label: TYPE_LABEL[r.type], short: SHORT[r.type],
      low: r.value_low.value ?? 0,
      high: r.value_high.value ?? 0 }));
  const top = rows[0];
  const summary = top
    ? `${top.label} has the largest value estimate, up to ${formatCompact(top.high)} ${money}.`
    : "No value estimate.";
  return (
    <ChartCard
      title="Value by type (high estimate)"
      summary={summary}
      chart={
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 56, bottom: 0, left: 8 }}>
            <CartesianGrid horizontal={false} stroke="var(--color-chart-grid)" />
            <XAxis type="number" tickFormatter={(v: number) => formatCompact(v)}
              tick={{ fontSize: 12, fill: "var(--color-text-muted)" }} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="short" width={84}
              tick={{ fontSize: 12, fill: "var(--color-text-muted)" }} tickLine={false} axisLine={false} />
            <Tooltip formatter={(v: number) => `${formatValue(v, "net sales")} ${money}`}
              labelFormatter={(_l: string, p: { payload?: { label?: string } }[]) => p?.[0]?.payload?.label ?? _l}
              cursor={{ fill: "var(--color-surface-muted)" }} />
            <Bar dataKey="high" name="High estimate" cursor="pointer" radius={[0, 4, 4, 0]}
              isAnimationActive={false}
              onClick={(entry: { type?: OppType }) => navigate(explorer(entry.type))}>
              {rows.map((r) => <Cell key={r.type} fill={TYPE_META[r.type].chart} />)}
              <LabelList dataKey="high" position="right" formatter={(v: number) => formatCompact(v)}
                style={{ fontSize: 12, fill: "var(--color-text)" }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      }
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Type</TableHead>
              <TableHead scope="col" className="text-right">Low estimate</TableHead>
              <TableHead scope="col" className="text-right">High estimate</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.type}>
                <TableCell>
                  <Link className="font-medium text-primary hover:underline" to={explorer(r.type)}>{r.label}</Link>
                </TableCell>
                <TableCell className="tabular text-right">{formatValue(r.low, "net sales")}</TableCell>
                <TableCell className="tabular text-right">{formatValue(r.high, "net sales")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    />
  );
}

function TopTable({ data }: { data: OverviewData }) {
  const money = useMoneyUnit();
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2">
        <div>
          <CardTitle>Top {data.top.length} opportunities</CardTitle>
          <CardDescription>Ranked by score across all engines.</CardDescription>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to="/opportunities">
            Open Explorer <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">#</TableHead>
              <TableHead scope="col">Type</TableHead>
              <TableHead scope="col">Customer</TableHead>
              <TableHead scope="col">Category</TableHead>
              <TableHead scope="col">Priority</TableHead>
              <TableHead scope="col" className="text-right">Score</TableHead>
              <TableHead scope="col" className="text-right">Value range, {money} (estimate)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.top.map((item) => (
              <TableRow key={item.opp_id}>
                <TableCell className="tabular text-muted">{item.rank}</TableCell>
                <TableCell><TypeBadge type={item.type} /></TableCell>
                <TableCell className="max-w-[16rem]">
                  <Link to={`/opportunities/${item.opp_id}`} title={customerLabel(item.customer)}
                    className="block truncate font-medium text-primary hover:underline">
                    {customerLabel(item.customer)}
                  </Link>
                </TableCell>
                <TableCell className="text-muted">{item.category ?? "—"}</TableCell>
                <TableCell><PriorityBadge level={item.priority} /></TableCell>
                <TableCell className="text-right"><Metric metric={item.score} label="score" /></TableCell>
                <TableCell className="whitespace-nowrap text-right">
                  <Metric metric={item.value_low} label="value low" hideUnit />
                  <span className="text-muted"> – </span>
                  <Metric metric={item.value_high} label="value high" hideUnit />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export function Overview() {
  const query = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  return (
    <section aria-labelledby="page-title" className="space-y-6">
      <PageHeader
        title={<span id="page-title">Overview</span>}
        subtitle="Where the opportunity is this week. Values are measured counts or estimates of net sales."
        actions={
          <Button asChild>
            <Link to="/opportunities">Open Explorer <ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
          </Button>
        }
      />
      <AsyncBoundary
        query={query}
        label="the overview"
        skeleton="cards"
        isEmpty={(d: OverviewData) => d.kpis.opportunities.value === 0}
        emptyTitle="No opportunities yet"
        empty="No opportunities for this as-of date. Run `revint opportunities build`."
      >
        {(data) => (
          <>
            <div className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
              <StatCard label="Opportunities" metric={data.kpis.opportunities} icon={Target}
                note="Across 4 engines" to="/opportunities" />
              <StatCard label="Customers" metric={data.kpis.customers} icon={Users} tone="measured"
                note="With at least one opportunity" />
              <StatCard label="Value, low estimate" metric={data.kpis.value_low} icon={Coins}
                note={<Badge tone="opportunity">Estimate</Badge>} />
              <StatCard label="Value, high estimate" metric={data.kpis.value_high} icon={Coins}
                note={<Badge tone="opportunity">Estimate</Badge>} />
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <ByTypeChart data={data} />
              <ValueChart data={data} />
            </div>
            <TopTable data={data} />
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}
