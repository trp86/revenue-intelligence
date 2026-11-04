// Story #135: the frontend foundation (spec 07 sections 4 to 6).
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ApiError, api } from "../api/client";
import { AsyncBoundary, Partial } from "../components/AsyncBoundary";
import { Metric } from "../components/Metric";
import { formatValue } from "../format";
import { mockApi, renderWithProviders } from "./render";

const DEFINITIONS = {
  definitions: [
    { id: "opp_score", group: "column", kind: "metric", text: "Score from 0 to 100.",
      applies_to: [], source: null, rule: null },
  ],
};

const base = { isPending: false, isError: false, error: null, data: undefined, refetch: () => {} };

describe("AC4 AsyncBoundary", () => {
  it("shows a loading state", () => {
    renderWithProviders(
      <AsyncBoundary query={{ ...base, isPending: true }} label="opportunities">
        {() => <p>data</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading opportunities");
  });

  it("shows an empty state that says why", () => {
    renderWithProviders(
      <AsyncBoundary query={{ ...base, data: [] as number[] }} isEmpty={(d) => d.length === 0}
        empty="No opportunities match these filters." label="opportunities">
        {() => <p>data</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("No opportunities match these filters.");
  });

  it("shows an error with a retry that refetches", async () => {
    let retried = 0;
    renderWithProviders(
      <AsyncBoundary query={{ ...base, isError: true, error: new ApiError(503, "not_ready",
        "Run the build."), refetch: () => (retried += 1) }} label="the overview">
        {() => <p>data</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Run the build.");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retried).toBe(1);
  });

  it("shows the data, and a partial region on its own", () => {
    renderWithProviders(
      <>
        <AsyncBoundary query={{ ...base, data: 3 }} label="x">{(d) => <p>value {d}</p>}</AsyncBoundary>
        <Partial title="AI suggestion">not available</Partial>
      </>,
    );
    expect(screen.getByText("value 3")).toBeInTheDocument();
    expect(screen.getByText(/not available/)).toBeInTheDocument();
  });
});

describe("AC5 Metric", () => {
  it("formats with one formatter and shows the unit", () => {
    expect(formatValue(12345.678, "net sales")).toBe("12,346");
    expect(formatValue(0.5, "share")).toBe("50%");
    expect(formatValue(19.99, "percent")).toBe("19.99%");
    expect(formatValue(null, "days")).toBe("â€”");
  });

  it("opens its definition on click and from the keyboard", async () => {
    mockApi({ "/definitions": DEFINITIONS });
    renderWithProviders(
      <Metric metric={{ value: 72.5, unit: "points", definition_id: "opp_score" }} label="score" />,
    );
    expect(screen.getByText("72.5")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Definition of score" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Score from 0 to 100.");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });
});

describe("AC3 the API client", () => {
  it("passes filters as query parameters and turns errors into ApiError", async () => {
    const calls = mockApi({
      "/opportunities": { total: 0, page: 1, page_size: 25, items: [] },
      "/opportunities/missing": { status: 404, body: { error: { code: "not_found",
        message: "no opportunity with that id" } } },
    });
    await api.opportunities({ type: "dormancy", page: 2, branch: "" });
    expect(calls[0]).toBe("/api/v1/opportunities?type=dormancy&page=2");
    await expect(api.opportunity("missing")).rejects.toMatchObject({ status: 404,
      code: "not_found" });
  });
});
