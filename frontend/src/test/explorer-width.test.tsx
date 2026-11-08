// Story #187: the Explorer uses the full width, and wide value ranges are compact.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppLayout } from "../components/layout/AppLayout";
import { ValueRange } from "../screens/Opportunities";
import { mockApi, renderWithProviders } from "./render";

const HEALTH = { status: "ready", as_of_date: "2020-02-29", net_sales_field: "Net_Amount_2",
  net_sales_provisional: true, built_at: null, message: null };

function layoutAt(route: string) {
  mockApi({ "/health": HEALTH, "/definitions": { definitions: [] } });
  renderWithProviders(<AppLayout><p>page</p></AppLayout>, route);
  return document.getElementById("main")!;
}

describe("story #187", () => {
  it("AC2 the Explorer list uses the full width; other pages keep a reading width", () => {
    expect(layoutAt("/opportunities").className).toContain("max-w-none");
  });

  it("AC2 the Overview keeps its reading width", () => {
    expect(layoutAt("/").className).toContain("max-w-7xl");
  });

  it("AC3 a range of a million or more is compact, with the full numbers in its title", () => {
    renderWithProviders(<ValueRange low={9174325} high={27522976} />);
    const range = screen.getByText("9.17M – 27.52M");
    expect(range).toHaveAttribute("title", "9,174,325 – 27,522,976");
  });

  it("AC3 a smaller range keeps its full numbers", () => {
    renderWithProviders(<ValueRange low={150} high={450} />);
    expect(screen.getByText("150 – 450")).toBeInTheDocument();
  });
});
