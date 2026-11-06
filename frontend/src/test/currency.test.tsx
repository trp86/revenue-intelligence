// Story #160: money values show the configured currency (display.currency, via /health).
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Metric } from "../components/Metric";
import { Overview } from "../screens/Overview";
import { summaryFor } from "../summaries";
import { DEFINITIONS, OVERVIEW } from "./fixtures";
import { mockApi, renderWithProviders } from "./render";

const health = (currency: string | null) => ({
  status: "ready", as_of_date: "2020-02-29", net_sales_field: "Net_Amount_2",
  net_sales_provisional: true, currency, built_at: null, message: null,
});

const money = { value: 1500, unit: "net sales", definition_id: "opp_value_low" };

describe("AC1 money values show the configured currency", () => {
  it("a net sales value shows the currency code as its unit", async () => {
    mockApi({ "/health": health("MMK"), "/definitions": DEFINITIONS });
    renderWithProviders(<Metric metric={money} label="value low" />);
    expect(await screen.findByText("MMK")).toBeInTheDocument();
    expect(screen.queryByText("net sales")).not.toBeInTheDocument();
  });

  it("a value in another unit is unchanged", async () => {
    mockApi({ "/health": health("MMK"), "/definitions": DEFINITIONS });
    renderWithProviders(<Metric metric={{ value: 3, unit: "orders", definition_id: "x" }} label="orders" />);
    expect(await screen.findByText("orders")).toBeInTheDocument();
    expect(screen.queryByText("MMK")).not.toBeInTheDocument();
  });

  it("the Overview chart summary names the currency", async () => {
    mockApi({ "/overview": OVERVIEW, "/health": health("MMK"), "/definitions": DEFINITIONS });
    renderWithProviders(<Overview />);
    expect(await screen.findByText(/has the largest value estimate: .+ to .+ MMK\./)).toBeInTheDocument();
  });

  it("the 'what happened' line uses the currency", () => {
    const facts = [
      { fact: "decline_pct", value: 0.5, unit: "share", definition_id: "d" },
      { fact: "prior_net_sales", value: 2000, unit: "net sales", definition_id: "p" },
      { fact: "current_net_sales", value: 1000, unit: "net sales", definition_id: "c" },
    ];
    expect(summaryFor("recovery", facts as never, null, "MMK")).toContain("1,000 MMK).");
    expect(summaryFor("recovery", facts as never, null)).toContain("1,000 net sales).");
  });
});

describe("AC2 an empty currency keeps the net sales label", () => {
  it("shows 'net sales' when no currency is configured", async () => {
    mockApi({ "/health": health(null), "/definitions": DEFINITIONS });
    renderWithProviders(<Metric metric={money} label="value low" />);
    expect(await screen.findByText("net sales")).toBeInTheDocument();
  });
});
