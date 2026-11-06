// The API contracts (docs/openapi.json, story #134), written by hand for the POC screens.

export type Level = "High" | "Medium" | "Low";
export type OppType = "dormancy" | "recovery" | "whitespace" | "crosssell";

export interface Metric {
  value: number | null;
  unit: string;
  definition_id: string;
}

export interface Health {
  status: "ready" | "not_ready";
  as_of_date: string | null;
  net_sales_field: string;
  net_sales_provisional: boolean;
  /** display.currency (story #160); null keeps the "net sales" label. */
  currency?: string | null;
  built_at: string | null;
  message: string | null;
}

export interface Definition {
  id: string;
  group: "column" | "evidence";
  kind: string;
  text: string;
  applies_to: string[];
  source: string | null;
  rule: string | null;
}

export interface Customer {
  customer_key: number;
  code: string | null;
  name: string | null;
  f_multi_identity: boolean;
}

export interface OpportunityItem {
  opp_id: string;
  type: OppType;
  rank: number;
  customer: Customer;
  category: string | null;
  branch: string | null;
  channel: string | null;
  as_of_date: string;
  score: Metric;
  priority: Level;
  confidence: Level;
  value_low: Metric;
  value_high: Metric;
  value_level: Level;
  reason_codes: string[];
}

export interface OpportunitiesPage {
  total: number;
  page: number;
  page_size: number;
  items: OpportunityItem[];
}

export interface Overview {
  as_of_date: string | null;
  kpis: { opportunities: Metric; customers: Metric; value_low: Metric; value_high: Metric };
  by_type: {
    type: OppType;
    count: Metric;
    by_priority: Record<Level, number>;
    value_low: Metric;
    value_high: Metric;
  }[];
  top: OpportunityItem[];
}

export interface Fact {
  fact: string;
  kind: "measured";
  value: number | string | null;
  unit: string;
  definition_id: string;
}

export interface OpportunityDetail extends OpportunityItem {
  measured: Fact[];
  estimate: {
    kind: "estimate";
    value_low: Metric;
    value_high: Metric;
    value_level: Level;
    method: string | null;
  };
  data_quality_notes: string[];
}

export interface BriefResponse {
  kind: "ai";
  opp_id: string;
  brief: {
    headline: string;
    explanation: string;
    recommendation: string;
    actions: { text: string; suggested_owner_role: string; evidence_ids: string[] }[];
    risks: string[];
    confidence_label: Level;
    evidence_ids_used: string[];
  };
  provenance: {
    model: string;
    prompt_version: string;
    generated_at: string;
    validation_status: string;
    review_status: string;
    cached: boolean;
  };
}

export interface OpportunityFilters {
  type?: OppType;
  priority?: Level;
  confidence?: Level;
  branch?: string;
  channel?: string;
  page?: number;
  page_size?: number;
  sort?: "rank" | "score" | "value_high";
}
