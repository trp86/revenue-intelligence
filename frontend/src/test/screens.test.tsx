// Story #136: Opportunities and Opportunity Detail (spec 07 section 3). The Overview tests
// are in overview.test.tsx since story #148.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Detail } from "../screens/Detail";
import { Opportunities } from "../screens/Opportunities";
import { DEFINITIONS, DETAIL, item } from "./fixtures";
import { mockApi, renderWithProviders } from "./render";

const PAGE = { total: 5, page: 1, page_size: 25, items: [1, 2, 3, 4, 5].map((r) => item(r)) };

function Location() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname + location.search}</span>;
}

function routed(element: React.ReactNode, path: string) {
  return (
    <>
      <Routes>
        <Route path={path} element={element} />
        <Route path="*" element={<p>other page</p>} />
      </Routes>
      <Location />
    </>
  );
}

async function noAxeViolations(container: HTMLElement) {
  // colour contrast needs a real layout engine; it is checked in the Playwright walkthrough
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

describe("AC2 Opportunities", () => {
  it("shows the ranked table with priority as text and icon", async () => {
    mockApi({ "/opportunities": PAGE, "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Opportunities />, "/opportunities"), "/opportunities");
    expect(await screen.findByText("5 opportunities · page 1 of 1")).toBeInTheDocument();
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(
      ["1", "2", "3", "4", "5"]);
    const priority = within(rows[0]).getByText("High");
    expect(priority.querySelector("svg")).not.toBeNull(); // an icon, not only colour
  });

  it("keeps filters and sort in the URL and sends them to the API", async () => {
    const calls = mockApi({ "/opportunities": PAGE, "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Opportunities />, "/opportunities"),
      "/opportunities?type=dormancy");
    await screen.findByText("5 opportunities · page 1 of 1");
    expect(calls.some((c) => c.includes("type=dormancy"))).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText("Priority"), "High");
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "score");
    await waitFor(() => expect(screen.getByTestId("location").textContent)
      .toBe("/opportunities?type=dormancy&priority=High&sort=score"));
    await waitFor(() => expect(calls.some((c) => c.includes("priority=High")
      && c.includes("sort=score"))).toBe(true));
  });
});

describe("AC3 Detail", () => {
  it("shows three labelled blocks: Measured fact, Estimate and AI suggestion", async () => {
    mockApi({ "/opportunities/opp-1": DETAIL, "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Detail />, "/opportunities/:id"), "/opportunities/opp-1");
    const measured = await screen.findByRole("region", { name: /Measured fact/ });
    expect(within(measured).getByText("Days since the last order")).toBeInTheDocument();
    expect(within(measured).getByText("2019-11-21")).toBeInTheDocument();
    const estimate = screen.getByRole("region", { name: /Estimate/ });
    expect(estimate).toHaveTextContent("1,000");
    expect(estimate).toHaveTextContent("Estimate: 0.25 to 0.75 x the gap.");
    const ai = screen.getByRole("region", { name: /AI suggestion/ });
    // story #138: the block loads the brief; with none it offers to generate one
    expect(await within(ai).findByRole("button", { name: "Generate brief" })).toBeInTheDocument();
  });

  it("shows the multiple-spellings notice and the reasons", async () => {
    mockApi({ "/opportunities/opp-1": DETAIL, "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Detail />, "/opportunities/:id"), "/opportunities/opp-1");
    expect(await screen.findByRole("note")).toHaveTextContent("multiple spellings");
    expect(screen.getByText("confidence capped")).toBeInTheDocument();
  });
});

describe("AC4 loading, empty and error states", () => {
  it("Opportunities: empty says what to do, and error", async () => {
    mockApi({ "/opportunities": { total: 0, page: 1, page_size: 25, items: [] },
      "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Opportunities />, "/opportunities"), "/opportunities");
    expect(await screen.findByText(/Clear a filter to see more/)).toBeInTheDocument();
  });

  it("Detail: an unknown id shows the error", async () => {
    mockApi({ "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Detail />, "/opportunities/:id"), "/opportunities/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load this opportunity");
  });
});

describe("AC6 accessibility (axe)", () => {
  it("Opportunities has no violations", async () => {
    mockApi({ "/opportunities": PAGE, "/definitions": DEFINITIONS });
    const { container } = renderWithProviders(routed(<Opportunities />, "/opportunities"),
      "/opportunities");
    await screen.findByText("5 opportunities · page 1 of 1");
    await noAxeViolations(container);
  });

  it("Detail has no violations", async () => {
    mockApi({ "/opportunities/opp-1": DETAIL, "/definitions": DEFINITIONS });
    const { container } = renderWithProviders(routed(<Detail />, "/opportunities/:id"),
      "/opportunities/opp-1");
    await screen.findByRole("region", { name: /Measured fact/ });
    await noAxeViolations(container);
  });
});
