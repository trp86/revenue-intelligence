// Story #147: the app layout, navigation and breadcrumbs.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useCrumbTitle } from "../components/layout/crumbs";
import { AppLayout } from "../components/layout/AppLayout";
import { PageHeader } from "../components/layout/PageHeader";
import { Metric } from "../components/Metric";
import { mockApi, renderWithProviders } from "./render";

const HEALTH = { status: "ready", as_of_date: "2020-02-29", net_sales_field: "Net_Amount_2",
  net_sales_provisional: true, built_at: null, message: null };
const DEFINITIONS = { definitions: [] };

function DetailPage() {
  useCrumbTitle("Dormant customer: Shop A");
  return <p>detail</p>;
}

function app(route: string) {
  return renderWithProviders(
    <AppLayout>
      <Routes>
        <Route path="/" element={<Link to="/opportunities">to explorer</Link>} />
        <Route path="/opportunities" element={<p>explorer</p>} />
        <Route path="/opportunities/:id" element={<DetailPage />} />
      </Routes>
    </AppLayout>,
    route,
  );
}

describe("AC1 the sidebar", () => {
  it("shows the app name and both screens with icons, Explorer as the main workspace", () => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    app("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Overview", "Opportunity ExplorerMain workspace"]);
    for (const link of links) expect(link.querySelector("svg")).not.toBeNull();
    expect(screen.getAllByText("Revenue Intelligence").length).toBeGreaterThan(0);
  });

  it("marks the active item with aria-current, not colour alone", () => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    app("/opportunities");
    const nav = screen.getByRole("navigation", { name: "Main" });
    const active = within(nav).getByRole("link", { name: /Opportunity Explorer/ });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active.className).toContain("font-semibold");
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });
});

describe("AC2 the menu on narrow screens", () => {
  it("opens a sheet with the navigation, and Escape closes it", async () => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    app("/");
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const sheet = await screen.findByRole("dialog", { name: "Menu" });
    expect(within(sheet).getByRole("link", { name: "Overview" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("closes after choosing a screen", async () => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    app("/");
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const sheet = await screen.findByRole("dialog", { name: "Menu" });
    await userEvent.click(within(sheet).getByRole("link", { name: /Opportunity Explorer/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("explorer")).toBeInTheDocument();
  });
});

describe("AC3 the top bar", () => {
  it.each([
    ["/", ["Overview"]],
    ["/opportunities", ["Overview", "Opportunities"]],
    ["/opportunities/opp-1", ["Overview", "Opportunities", "Dormant customer: Shop A"]],
  ])("shows the breadcrumbs on %s", async (route, trail) => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    app(route);
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    await waitFor(() => expect(within(crumbs).getAllByRole("listitem").map((li) => li.textContent))
      .toEqual(trail));
    expect(within(crumbs).getByText(trail[trail.length - 1])).toHaveAttribute("aria-current", "page");
  });

  it("shows the as-of date and no net sales field badge (story #161)", async () => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    app("/");
    expect(await screen.findByText("2020-02-29")).toBeInTheDocument();
    expect(screen.getByRole("banner")).not.toHaveTextContent(/Net_Amount_2|provisional/);
  });

  it("the definition of a net sales value names the field and that it is provisional (story #161)",
    async () => {
      mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
      renderWithProviders(
        <Metric metric={{ value: 1500, unit: "net sales", definition_id: "opp_value_low" }} label="value low" />,
      );
      await userEvent.click(screen.getByRole("button", { name: "Definition of value low" }));
      expect(await screen.findByRole("tooltip")).toHaveTextContent(
        "Net sales are taken from Net_Amount_2 (provisional).",
      );
    });

  it("the definition of a value that is not net sales does not mention the field", async () => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    renderWithProviders(<Metric metric={{ value: 3, unit: "orders", definition_id: "x" }} label="orders" />);
    await userEvent.click(screen.getByRole("button", { name: "Definition of orders" }));
    expect(await screen.findByRole("tooltip")).not.toHaveTextContent("Net_Amount_2");
  });

  it("warns when the data is not built", async () => {
    mockApi({ "/health": { ...HEALTH, status: "not_ready", as_of_date: null,
      message: "run the build" }, "/definitions": DEFINITIONS });
    app("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Data not built: run the build");
  });

  it("warns when the API is not reachable", async () => {
    globalThis.fetch = (async () => { throw new TypeError("offline"); }) as typeof fetch;
    app("/");
    expect(await screen.findByText(/API not reachable/)).toBeInTheDocument();
  });
});

describe("AC5 keyboard and focus", () => {
  it("has a skip link to the main region", () => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    app("/");
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip).toHaveAttribute("href", "#main");
    expect(document.getElementById("main")?.tagName).toBe("MAIN");
  });

  it("moves focus to the main region after a route change", async () => {
    mockApi({ "/health": HEALTH, "/definitions": DEFINITIONS });
    app("/");
    await userEvent.click(screen.getByRole("link", { name: "to explorer" }));
    await waitFor(() => expect(document.getElementById("main")).toHaveFocus());
  });
});

describe("AC4 PageHeader", () => {
  it("shows the title, subtitle and actions", () => {
    renderWithProviders(
      <PageHeader title="Opportunity Explorer" subtitle="64,543 opportunities"
        actions={<button type="button">Clear filters</button>} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Opportunity Explorer" })).toBeInTheDocument();
    expect(screen.getByText("64,543 opportunities")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });
});
