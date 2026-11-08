// Story #136: the Opportunity Detail (spec 07 section 3). The Overview tests are in
// overview.test.tsx (#148), the Explorer tests in explorer.test.tsx (#149).
import { screen, within } from "@testing-library/react";
import axe from "axe-core";
import { Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Detail } from "../screens/Detail";
import { DEFINITIONS, DETAIL } from "./fixtures";
import { mockApi, renderWithProviders } from "./render";


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

describe("AC3 Detail", () => {
  it("shows three labelled blocks: Measured fact, Estimate and AI suggestion", async () => {
    mockApi({ "/opportunities/opp-1": DETAIL, "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Detail />, "/opportunities/:id"), "/opportunities/opp-1");
    const measured = await screen.findByRole("region", { name: /Measured fact/ });
    expect(within(measured).getByText("Days since the last order")).toBeInTheDocument();
    expect(within(measured).getByText("2019-11-21")).toBeInTheDocument();
    const estimate = screen.getByRole("region", { name: /Estimate/ });
    expect(estimate).toHaveTextContent("1,000");
    expect(estimate).toHaveTextContent(/Based on 25% to 75% of /); // plain text since story #171
    const ai = screen.getByRole("region", { name: /Suggested next steps/ });
    // story #138: the block loads the brief; with none it offers to generate one
    expect(await within(ai).findByRole("button", { name: "Get suggestions" })).toBeInTheDocument();
  });

  it("shows the multiple-spellings notice and the reasons", async () => {
    mockApi({ "/opportunities/opp-1": DETAIL, "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Detail />, "/opportunities/:id"), "/opportunities/opp-1");
    expect(await screen.findByRole("note")).toHaveTextContent("multiple spellings");
    expect(screen.getByText("confidence capped")).toBeInTheDocument();
  });
});

describe("AC4 loading, empty and error states", () => {
  it("Detail: an unknown id shows the error", async () => {
    mockApi({ "/definitions": DEFINITIONS });
    renderWithProviders(routed(<Detail />, "/opportunities/:id"), "/opportunities/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load this opportunity");
  });
});

describe("AC6 accessibility (axe)", () => {
  it("Detail has no violations", async () => {
    mockApi({ "/opportunities/opp-1": DETAIL, "/definitions": DEFINITIONS });
    const { container } = renderWithProviders(routed(<Detail />, "/opportunities/:id"),
      "/opportunities/opp-1");
    await screen.findByRole("region", { name: /Measured fact/ });
    await noAxeViolations(container);
  });
});
