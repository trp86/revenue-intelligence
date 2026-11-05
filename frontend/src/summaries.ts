// "What happened", in one line, built only from the measured facts of an opportunity (story #149;
// the Detail page uses it too, story #150). Deterministic: no AI, and no number that is not a fact.
import type { Fact, OppType } from "./api/types";
import { formatValue } from "./format";

function value(facts: Fact[], name: string): number | string | null {
  return facts.find((f) => f.fact === name)?.value ?? null;
}

function fmt(facts: Fact[], name: string): string {
  const fact = facts.find((f) => f.fact === name);
  return fact ? formatValue(fact.value, fact.unit) : "—";
}

export function summaryFor(type: OppType, facts: Fact[], category?: string | null): string {
  const has = (...names: string[]) => names.every((n) => value(facts, n) !== null);
  switch (type) {
    case "dormancy":
      return has("days_since_last_order", "median_interval_days")
        ? `No order for ${fmt(facts, "days_since_last_order")} days; this customer usually orders every ` +
          `${fmt(facts, "median_interval_days")} days.`
        : "This customer has stopped ordering compared with its usual rhythm.";
    case "recovery":
      return has("decline_pct", "prior_net_sales", "current_net_sales")
        ? `Net sales fell ${fmt(facts, "decline_pct")} on the same months last year ` +
          `(${fmt(facts, "prior_net_sales")} → ${fmt(facts, "current_net_sales")} net sales).`
        : "Net sales fell against the same months last year.";
    case "whitespace":
      return has("n_buying_peers", "n_peers")
        ? `${fmt(facts, "n_buying_peers")} of ${fmt(facts, "n_peers")} similar customers buy ` +
          `${category ?? "this category"}; this customer has not bought it recently.`
        : `Most similar customers buy ${category ?? "this category"}; this customer does not.`;
    case "crosssell":
      return has("confidence", "support")
        ? `${fmt(facts, "confidence")} of customers who buy a related category also buy ` +
          `${category ?? "this one"} (${fmt(facts, "support")} customers); this customer never has.`
        : `Customers who buy a related category often add ${category ?? "this one"}.`;
  }
}
