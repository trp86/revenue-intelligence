// Story #148: the Overview redesign (KPI cards, charts with table alternatives, the top 10).
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { formatCompact } from "../format";
import { Overview } from "../screens/Overview";
import { DEFINITIONS, OVERVIEW } from "./fixtures";
import { mockApi, renderWithProviders } from "./render";

function Location() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname + location.search}</span>;
}

function page() {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/opportunities" element={<p>explorer</p>} />
        <Route path="/opportunities/:id" element={<p>detail</p>} />
      </Routes>
      <Location />
    </>,
  );
}

async function ready() {
  mockApi({ "/overview": OVERVIEW, "/definitions": DEFINITIONS });
  const view = page();
  await screen.findByRole("region", { name: "Opportunities by type and priority" });
  return view;
}

describe("AC1 KPI cards", () => {
  it("shows four cards with an icon badge, a label and the number", async () => {
    await ready();
    for (const [label, value] of [["Opportunities", "5"], ["Customers", "5"],
      ["Value, low estimate", "15,000"], ["Value, high estimate", "45,000"]]) {
      const name = screen.getByText(label, { selector: "span" });
      const card = name.closest("div.rounded-lg") as HTMLElement;
      expect(card.querySelector("svg"), label).not.toBeNull();
      expect(within(card).getByText(value)).toBeInTheDocument();
      expect(within(card).getByRole("button", { name: `Definition of ${label}` })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Estimate")).toHaveLength(2);
  });
});

describe("AC2 charts with a table alternative", () => {
  it("names each chart by its summary", async () => {
    await ready();
    expect(screen.getByRole("img", { name: /Dormant customer has the most opportunities \(3 of 5\); 2 are High priority/ }))
      .toBeInTheDocument();
    expect(screen.getByRole("img", { name: new RegExp(`Category whitespace has the largest value estimate, up to ${formatCompact(27000)}`) }))
      .toBeInTheDocument();
  });

  it("shows the same numbers as a table, and back", async () => {
    await ready();
    const card = screen.getByRole("region", { name: "Opportunities by type and priority" });
    const toggle = within(card).getByRole("button", { name: "Show as table" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    const rows = within(within(card).getByRole("table")).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "TypeHighMediumLowTotal",
      "Dormant customer2103",
      "Category whitespace0112",
    ]);
    await userEvent.click(within(card).getByRole("button", { name: "Show as chart" }));
    expect(within(card).getByRole("img")).toBeInTheDocument();
  });

  it("lists the value estimates in the value table, sorted by the high estimate", async () => {
    await ready();
    const card = screen.getByRole("region", { name: "Value by type (high estimate)" });
    await userEvent.click(within(card).getByRole("button", { name: "Show as table" }));
    const rows = within(within(card).getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual(["Category whitespace9,00027,000",
      "Dormant customer6,00018,000"]);
  });
});

describe("AC3 every view opens the filtered Explorer", () => {
  it("a type in the chart table opens the Explorer for that type", async () => {
    await ready();
    const card = screen.getByRole("region", { name: "Opportunities by type and priority" });
    await userEvent.click(within(card).getByRole("button", { name: "Show as table" }));
    await userEvent.click(within(card).getByRole("link", { name: "Dormant customer" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/opportunities?type=dormancy");
  });

  it("a type and priority cell opens the Explorer for both", async () => {
    await ready();
    const card = screen.getByRole("region", { name: "Opportunities by type and priority" });
    await userEvent.click(within(card).getByRole("button", { name: "Show as table" }));
    await userEvent.click(within(card).getByRole("link", { name: "Dormant customer, High priority: 2" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/opportunities?type=dormancy&priority=High");
  });

  it("the Opportunities KPI opens the Explorer", async () => {
    await ready();
    await userEvent.click(screen.getAllByRole("link", { name: "Open in Explorer" })[0]);
    expect(screen.getByTestId("location")).toHaveTextContent("/opportunities");
  });
});

describe("AC4 the top 10", () => {
  it("shows rank, type and priority pills, score and value range, linking to Detail", async () => {
    await ready();
    const card = screen.getByText(/^Top 5 opportunities$/).closest("div.rounded-lg") as HTMLElement;
    const rows = within(card).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    const first = rows[0];
    expect(within(first).getByText("Dormant customer").closest("span")?.querySelector("svg")).not.toBeNull();
    expect(within(first).getByText("High").querySelector("svg")).not.toBeNull();
    const link = within(first).getAllByRole("link").find((a) => a.getAttribute("href") === "/opportunities/opp-1");
    expect(link?.textContent).toBe("Shop 1 · C1");
    expect(first).toHaveTextContent("1,000");
    expect(first).toHaveTextContent("3,000");
  });
});

describe("AC5 loading, empty and error states", () => {
  it("shows card skeletons while loading, then an error with Retry", async () => {
    mockApi({ "/overview": { status: 503, body: { error: { code: "not_ready",
      message: "Run `revint opportunities build`." } } }, "/definitions": DEFINITIONS });
    const { container } = page();
    expect(container.querySelector('[data-skeleton="cards"]')).not.toBeNull();
    expect(await screen.findByRole("alert")).toHaveTextContent("revint opportunities build");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows an empty state that says what to do", async () => {
    mockApi({ "/overview": { ...OVERVIEW, kpis: { ...OVERVIEW.kpis, opportunities:
      { value: 0, unit: "opportunities", definition_id: "opp_id" } } }, "/definitions": DEFINITIONS });
    page();
    expect(await screen.findByText("No opportunities yet")).toBeInTheDocument();
    expect(screen.getByText(/Run `revint opportunities build`/)).toBeInTheDocument();
  });

  it("has no axe violations (contrast is checked in the browser walkthrough)", async () => {
    const { container } = await ready();
    const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
