// Opportunity Detail (spec 07 sections 3 and 6, story #150). It answers, in order: what happened
// (one line from the measured facts), where (customer, branch, channel, category), why it matters
// (value range, priority, confidence, score) and what to do (the AI suggestion). Measured fact,
// Estimate and AI suggestion are separate blocks.
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, MapPin, Tag } from "lucide-react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { OpportunityDetail } from "../api/types";
import { AiBriefBlock } from "../components/AiBrief";
import { AsyncBoundary } from "../components/AsyncBoundary";
import { AiPanel, EstimatePanel, EvidencePanel } from "../components/detail/panels";
import { ConfidenceBadge, customerLabel, PriorityBadge, TYPE_LABEL, TypeBadge } from "../components/labels";
import { useCrumbTitle } from "../components/layout/crumbs";
import { Metric } from "../components/Metric";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { summaryFor } from "../summaries";
import { useMoneyUnit } from "../money";

function HeaderCard({ o }: { o: OpportunityDetail }) {
  const money = useMoneyUnit();
  const where = [
    o.branch && { label: "Branch", value: o.branch },
    o.channel && { label: "Channel", value: o.channel },
    { label: "Category", value: o.category ?? "Whole customer" },
  ].filter(Boolean) as { label: string; value: string }[];
  return (
    <Card className="p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <TypeBadge type={o.type} />
          <h1 id="page-title" className="break-words font-heading text-2xl font-bold text-text md:text-[28px]">
            {customerLabel(o.customer)}
          </h1>
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-4 w-4" aria-hidden="true" />
              {where.map((w) => `${w.label}: ${w.value}`).join(" · ")}
            </span>
            <span>Rank #{o.rank} {"·"} as of {o.as_of_date}</span>
          </p>
        </div>
        <dl className="grid grid-cols-3 gap-4 text-sm" aria-label="Why it matters">
          <div>
            <dt className="text-xs font-medium text-muted">Priority</dt>
            <dd className="mt-1"><PriorityBadge level={o.priority} /></dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-muted">Confidence</dt>
            <dd className="mt-1"><ConfidenceBadge level={o.confidence} /></dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-muted">Score</dt>
            <dd className="mt-1 font-semibold"><Metric metric={o.score} label="score" /></dd>
          </div>
        </dl>
      </div>
      <div className="mt-4 rounded-md border-l-4 border-measured bg-measured-bg p-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-measured">What happened</p>
        <p className="mt-1 text-text">{summaryFor(o.type, o.measured, o.category, money)}</p>
      </div>
      {o.customer.f_multi_identity && (
        <p role="note" className="mt-3 flex items-start gap-2 rounded-md bg-warn-bg p-3 text-sm text-warn">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          This customer code may stand for more than one customer (multiple spellings).
        </p>
      )}
    </Card>
  );
}

function Reasons({ o }: { o: OpportunityDetail }) {
  if (o.reason_codes.length === 0 && o.data_quality_notes.length === 0) return null;
  return (
    <Card className="p-4 md:p-5">
      <h2 className="flex items-center gap-2 font-heading text-base font-semibold text-text">
        <Tag className="h-4 w-4 text-muted" aria-hidden="true" /> Why it was flagged
      </h2>
      <ul className="mt-3 flex flex-wrap gap-2" aria-label="Reasons">
        {o.reason_codes.map((r) => (
          <li key={r}><Badge tone="neutral">{r.replaceAll("_", " ")}</Badge></li>
        ))}
      </ul>
      {o.data_quality_notes.length > 0 && (
        <ul className="mt-3 space-y-2" aria-label="Data quality notes">
          {o.data_quality_notes.map((n) => (
            <li key={n} className="flex items-start gap-2 rounded-md bg-warn-bg p-2 text-sm text-warn">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {n}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function Detail() {
  const { id = "" } = useParams();
  const query = useQuery({ queryKey: ["opportunity", id], queryFn: () => api.opportunity(id) });
  useCrumbTitle(query.data ? `${TYPE_LABEL[query.data.type]}: ${customerLabel(query.data.customer)}` : null);
  return (
    <section aria-labelledby="page-title" className="space-y-4">
      <AsyncBoundary query={query} label="this opportunity" skeleton="detail">
        {(o) => (
          <>
            <HeaderCard o={o} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <EvidencePanel facts={o.measured} />
              <EstimatePanel estimate={o.estimate} />
            </div>
            <AiPanel>
              <AiBriefBlock oppId={o.opp_id} />
            </AiPanel>
            <Reasons o={o} />
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}
