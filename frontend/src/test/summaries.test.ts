// Story #149: "what happened" is one line per engine, built only from the measured facts.
import { describe, expect, it } from "vitest";

import type { Fact } from "../api/types";
import { summaryFor } from "../summaries";

const fact = (name: string, value: number | string, unit: string): Fact => ({
  fact: name, kind: "measured", value, unit, definition_id: `ev_${name}`,
});

describe("summaryFor", () => {
  it("dormancy: days quiet against the usual interval", () => {
    expect(summaryFor("dormancy", [fact("days_since_last_order", 100, "days"),
      fact("median_interval_days", 30, "days")]))
      .toBe("No order for 100 days; this customer usually orders every 30 days.");
  });

  it("recovery: the fall on last year with both amounts", () => {
    expect(summaryFor("recovery", [fact("decline_pct", 53.98, "percent"),
      fact("prior_net_sales", 300000, "net sales"), fact("current_net_sales", 138000, "net sales")]))
      .toBe("Net sales fell 53.98% on the same months last year (300,000 → 138,000 net sales).");
  });

  it("whitespace: buying peers out of peers, and the category", () => {
    expect(summaryFor("whitespace", [fact("n_buying_peers", 3, "customers"),
      fact("n_peers", 4, "customers")], "Air care"))
      .toBe("3 of 4 similar customers buy Air care; this customer has not bought it recently.");
  });

  it("cross-sell: confidence and support, and the category", () => {
    expect(summaryFor("crosssell", [fact("confidence", 0.6667, "share"),
      fact("support", 4, "customers")], "Insect control"))
      .toBe("66.67% of customers who buy a related category also buy Insect control (4 customers); "
        + "this customer never has.");
  });

  it("falls back to a plain sentence without numbers when a fact is missing", () => {
    for (const type of ["dormancy", "recovery", "whitespace", "crosssell"] as const) {
      expect(summaryFor(type, [])).not.toMatch(/\d/);
    }
  });
});
