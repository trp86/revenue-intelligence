// Synthetic API answers for the screen tests (story #136). No real customer data.
import type { OpportunityDetail, OpportunityItem, Overview } from "../api/types";

const metric = (value: number, unit: string, definition_id: string) => ({ value, unit, definition_id });

export function item(rank: number, overrides: Partial<OpportunityItem> = {}): OpportunityItem {
  return {
    opp_id: `opp-${rank}`,
    type: "dormancy",
    rank,
    customer: { customer_key: rank, code: `C${rank}`, name: `Shop ${rank}`, f_multi_identity: false },
    category: null,
    branch: "Magway",
    channel: "GT",
    as_of_date: "2020-02-29",
    score: metric(90 - rank, "points", "opp_score"),
    priority: rank <= 2 ? "High" : rank <= 4 ? "Medium" : "Low",
    confidence: "Medium",
    value_low: metric(1000 * rank, "net sales", "opp_value_low"),
    value_high: metric(3000 * rank, "net sales", "opp_value_high"),
    value_level: "High",
    reason_codes: ["beyond_own_interval", "beyond_min_days"],
    ...overrides,
  };
}

export const OVERVIEW: Overview = {
  as_of_date: "2020-02-29",
  kpis: {
    opportunities: metric(5, "opportunities", "opp_id"),
    customers: metric(5, "customers", "opp_customer_key"),
    value_low: metric(15000, "net sales", "opp_value_low"),
    value_high: metric(45000, "net sales", "opp_value_high"),
  },
  by_type: [
    { type: "dormancy", count: metric(3, "opportunities", "opp_type"),
      by_priority: { High: 2, Medium: 1, Low: 0 },
      value_low: metric(6000, "net sales", "opp_value_low"),
      value_high: metric(18000, "net sales", "opp_value_high") },
    { type: "whitespace", count: metric(2, "opportunities", "opp_type"),
      by_priority: { High: 0, Medium: 1, Low: 1 },
      value_low: metric(9000, "net sales", "opp_value_low"),
      value_high: metric(27000, "net sales", "opp_value_high") },
  ],
  top: [1, 2, 3, 4, 5].map((r) => item(r)),
};

export const DETAIL: OpportunityDetail = {
  ...item(1, { customer: { customer_key: 1, code: "C1", name: "Shop 1", f_multi_identity: true },
    reason_codes: ["beyond_own_interval", "confidence_capped"] }),
  measured: [
    { fact: "days_since_last_order", kind: "measured", value: 100, unit: "days",
      definition_id: "ev_days_since_last_order" },
    { fact: "median_interval_days", kind: "measured", value: 30, unit: "days",
      definition_id: "ev_median_interval_days" },
    { fact: "last_order_date", kind: "measured", value: "2019-11-21", unit: "date",
      definition_id: "ev_last_order_date" },
  ],
  estimate: {
    kind: "estimate",
    value_low: metric(1000, "net sales", "opp_value_low"),
    value_high: metric(3000, "net sales", "opp_value_high"),
    value_level: "High",
    method: "Estimate: 0.25 to 0.75 x the gap.",
    low_factor: 0.25,
    high_factor: 0.75,
  },
  data_quality_notes: ["The customer code may stand for more than one customer (f_multi_identity)."],
};

export const DEFINITIONS = {
  definitions: [
    { id: "opp_score", group: "column", kind: "metric", text: "Score from 0 to 100.",
      applies_to: [], source: null, rule: null },
  ],
};
