// A chart with a text summary and a "Show as table" alternative (spec 07 section 7, story #148).
// The summary is the chart's accessible name; the table holds the same numbers, with links.
import { BarChart3, Table2 } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { Button } from "../ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";

export function ChartCard({
  title,
  summary,
  chart,
  table,
}: {
  title: string;
  summary: string;
  chart: ReactNode;
  table: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const titleId = useId();
  return (
    <Card aria-labelledby={titleId} role="region">
      <CardHeader className="flex-row items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle id={titleId}>{title}</CardTitle>
          <CardDescription>{summary}</CardDescription>
        </div>
        <Button variant="outline" size="sm" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
          {asTable ? <BarChart3 className="h-4 w-4" aria-hidden="true" /> : <Table2 className="h-4 w-4" aria-hidden="true" />}
          {asTable ? "Show as chart" : "Show as table"}
        </Button>
      </CardHeader>
      <CardContent>
        {asTable ? table : (
          <div role="img" aria-label={summary} className="h-72 w-full">
            {chart}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
