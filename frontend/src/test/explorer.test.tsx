// Story #149: the Opportunity Explorer as the main working screen.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Opportunities } from "../screens/Opportunities";
import { DEFINITIONS, DETAIL, item } from "./fixtures";
import { mockApi, renderWithProviders } from "./render";

const PAGE = { total: 5, page: 1, page_size: 25, items: [1, 2, 3, 4, 5].map((r) => item(r)) };

function Location() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname + location.search}</span>;
}

function page(route = "/opportunities", routes: Record<string, unknown> = {}) {
  const calls = mockApi({ "/opportunities": PAGE, "/opportunities/opp-1": DETAIL,
    "/definitions": DEFINITIONS, ...routes });
  const view = renderWithProviders(
    <>
      <Routes>
        <Route path="/opportunities" element={<Opportunities />} />
        <Route path="/opportunities/:id" element={<p>detail page</p>} />
      </Routes>
      <Location />
    </>,
    route,
  );
  return { ...view, calls };
}

const location = () => screen.getByTestId("location").textContent;

describe("AC1 type tabs and filter bar", () => {
  it("filters by type with toggle buttons", async () => {
    const { calls } = page();
    await screen.findByText("5 opportunities");
    const tabs = screen.getByRole("group", { name: "Opportunity type" });
    expect(within(tabs).getByRole("button", { name: "All types" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(tabs).getByRole("button", { name: "Revenue recovery" }));
    expect(location()).toBe("/opportunities?type=recovery");
    expect(within(tabs).getByRole("button", { name: "Revenue recovery" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(calls.some((c) => c.includes("type=recovery"))).toBe(true));
  });

  it("filters by priority, confidence and branch, and sorts", async () => {
    const { calls } = page();
    await screen.findByText("5 opportunities");
    await userEvent.selectOptions(screen.getByLabelText("Priority"), "High");
    await userEvent.selectOptions(screen.getByLabelText("Confidence"), "Medium");
    await userEvent.type(screen.getByLabelText("Branch"), "Magway{Enter}");
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "score");
    expect(location()).toBe("/opportunities?priority=High&confidence=Medium&branch=Magway&sort=score");
    await waitFor(() => expect(calls.some((c) => c.includes("priority=High") && c.includes("confidence=Medium")
      && c.includes("branch=Magway") && c.includes("sort=score"))).toBe(true));
  });
});

describe("AC2 filter chips", () => {
  it("shows each active filter as a removable chip, and Clear all", async () => {
    page("/opportunities?type=dormancy&priority=High&branch=Magway");
    await screen.findByText("5 opportunities");
    const chips = screen.getByRole("group", { name: "Active filters" });
    expect(within(chips).getByText("Type: Dormant customer")).toBeInTheDocument();
    await userEvent.click(within(chips).getByRole("button", { name: "Remove filter Priority: High" }));
    expect(location()).toBe("/opportunities?type=dormancy&branch=Magway");
    await userEvent.click(within(chips).getByRole("button", { name: "Clear all" }));
    expect(location()).toBe("/opportunities");
    expect(screen.queryByRole("group", { name: "Active filters" })).not.toBeInTheDocument();
  });
});

describe("AC3 the table", () => {
  it("shows rank, type, customer, category, priority and confidence pills, score and value", async () => {
    page();
    await screen.findByText("5 opportunities");
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(within(rows[0]).getAllByRole("columnheader").map((h) => h.textContent?.trim())).toEqual([
      "Rank", "Type", "Customer and category", "Priority", "Confidence", "Score",
      "Value (estimate)", "Preview",
    ]);
    // one definition per column in the header, instead of one per number
    expect(within(rows[0]).getByRole("button", { name: "Definition of score" })).toBeInTheDocument();
    expect(within(rows[0]).getByRole("button", { name: "Definition of value (estimate)" })).toBeInTheDocument();
    const first = rows[1];
    expect(within(first).queryAllByRole("button", { name: /^Definition of/ })).toHaveLength(0);
    expect(within(first).getAllByRole("cell")[0].textContent).toBe("1");
    expect(within(first).getByText("High").querySelector("svg")).not.toBeNull();
    expect(within(first).getByText("Medium").closest("[data-level]")?.querySelector("svg")).not.toBeNull();
    expect(within(first).getByText("Whole customer")).toBeInTheDocument(); // no category
    expect(within(first).getByText("Dormant")).toHaveAttribute("title", "Dormant customer");
    expect(first).toHaveTextContent("1,000");
    expect(first).toHaveTextContent("3,000");
  });

  it("marks the sorted column with aria-sort", async () => {
    page("/opportunities?sort=score");
    await screen.findByText("5 opportunities");
    expect(screen.getByRole("columnheader", { name: "Score" })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: "Rank" })).not.toHaveAttribute("aria-sort");
  });

  it("opens the Detail page from the customer link", async () => {
    page();
    await screen.findByText("5 opportunities");
    await userEvent.click(screen.getAllByRole("link")[0]);
    expect(location()).toBe("/opportunities/opp-1");
  });
});

describe("AC4 the preview panel", () => {
  it("asks for a selection, then shows what happened and why it matters", async () => {
    page();
    await screen.findByText("5 opportunities");
    expect(screen.getByText(/Select an opportunity to preview/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Preview Shop 1 · C1" }));
    expect(location()).toBe("/opportunities?selected=opp-1");
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(within(preview).getByText(/No order for 100 days; this customer usually orders every 30 days\./))
      .toBeInTheDocument();
    expect(within(preview).getByText("Why it matters")).toBeInTheDocument();
    expect(within(preview).getByRole("link", { name: /Open details/ })).toHaveAttribute("href", "/opportunities/opp-1");
    expect(screen.getByRole("button", { name: "Preview Shop 1 · C1" })).toHaveAttribute("aria-pressed", "true");
  });

  it("selects a row by clicking it", async () => {
    page();
    await screen.findByText("5 opportunities");
    await userEvent.click(within(screen.getByRole("table")).getAllByRole("row")[1].querySelector("td") as HTMLElement);
    expect(location()).toBe("/opportunities?selected=opp-1");
  });
});

describe("AC5 the URL holds the state", () => {
  it("restores filters, sort, page and the selection from a shared link", async () => {
    const { calls } = page("/opportunities?type=dormancy&sort=value_high&page=2&selected=opp-1");
    await screen.findByText("5 opportunities");
    expect(calls.some((c) => c.includes("type=dormancy") && c.includes("sort=value_high")
      && c.includes("page=2"))).toBe(true);
    expect(await screen.findByRole("region", { name: "Preview" })).toBeInTheDocument();
    expect(screen.getByLabelText("Sort by")).toHaveValue("value_high");
  });

  it("goes to the next page and keeps the filters", async () => {
    page("/opportunities?type=dormancy", { "/opportunities": { ...PAGE, total: 60 } });
    await screen.findByText("60 opportunities");
    await userEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(location()).toBe("/opportunities?type=dormancy&page=2");
  });
});

describe("AC6 empty, loading and error states", () => {
  it("says why nothing matches and offers Clear filters", async () => {
    page("/opportunities?priority=High", { "/opportunities": { ...PAGE, total: 0, items: [] } });
    expect(await screen.findByText("No opportunities match")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(location()).toBe("/opportunities");
  });

  it("shows a table skeleton while loading and an error with Retry", async () => {
    const { container } = page("/opportunities", { "/opportunities": { status: 503,
      body: { error: { code: "not_ready", message: "Run the build." } } } });
    expect(container.querySelector('[data-skeleton="table"]')).not.toBeNull();
    expect(await screen.findByRole("alert")).toHaveTextContent("Run the build.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("has no axe violations with a selection (contrast is checked in the browser)", async () => {
    const { container } = page("/opportunities?selected=opp-1");
    await screen.findByRole("region", { name: "Preview" });
    const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
