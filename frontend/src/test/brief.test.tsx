// Story #138 AC4: the AI suggestion block on the Detail screen.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AiBriefBlock } from "../components/AiBrief";
import { mockApi, renderWithProviders } from "./render";

const BRIEF = {
  kind: "ai",
  opp_id: "opp-1",
  brief: {
    headline: "Win back a quiet customer",
    explanation: "It has not ordered for 100 days against a usual 30.",
    recommendation: "Call this week.",
    actions: [{ text: "Call the buyer", suggested_owner_role: "Sales rep", evidence_ids: [] }],
    risks: ["The customer may have moved"],
    confidence_label: "Medium",
    evidence_ids_used: [],
  },
  provenance: { model: "gemini-2.5-flash", prompt_version: "system.v1+dormancy.v1@abc",
    generated_at: "2026-11-03T10:15:00", validation_status: "valid", review_status: "Draft",
    cached: false },
};
const NO_BRIEF = { status: 404, body: { error: { code: "no_brief",
  message: "this opportunity has no AI brief yet" } } };

// story #150: Generate asks for confirmation first
async function generateWithConfirm() {
  await userEvent.click(await screen.findByRole("button", { name: "Get suggestions" }));
  const dialog = await screen.findByRole("dialog", { name: "Get suggested next steps?" });
  await userEvent.click(within(dialog).getByRole("button", { name: "Get suggestions" }));
}

describe("AC4 the AI suggestion block", () => {
  it("shows the brief labelled as AI with its provenance", async () => {
    mockApi({ "/opportunities/opp-1/brief": BRIEF });
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    expect(await screen.findByText("Win back a quiet customer")).toBeInTheDocument();
    expect(screen.getByText("Call the buyer")).toBeInTheDocument();
    expect(screen.getByText("The customer may have moved")).toBeInTheDocument();
    // story #170: folded into "About this suggestion"
    expect(screen.getByText("About this suggestion").closest("details")).not.toHaveAttribute("open");
    const provenance = screen.getByText(/Written by AI from the measured facts/);
    expect(provenance).toHaveTextContent("gemini-2.5-flash");
    expect(provenance).toHaveTextContent("system.v1+dormancy.v1@abc");
    expect(provenance).toHaveTextContent("2026-11-03 10:15");
  });

  it("offers Generate when there is no brief, and shows it after", async () => {
    let posted = false;
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/brief") && init?.method === "POST") {
        posted = true;
        return new Response(JSON.stringify(BRIEF), { status: 200 });
      }
      return new Response(JSON.stringify(NO_BRIEF.body), { status: 404 });
    }) as typeof fetch;
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    expect(await screen.findByText(/No suggestions yet for this customer/)).toBeInTheDocument();
    await generateWithConfirm();
    expect(await screen.findByText("Win back a quiet customer")).toBeInTheDocument();
    expect(posted).toBe(true);
  });

  it("shows a clear message when generation fails, and keeps the button", async () => {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ error: { code: "ai_unavailable",
          message: "the AI brief is not available now (Gemini error 503)" } }), { status: 503 });
      }
      return new Response(JSON.stringify(NO_BRIEF.body), { status: 404 });
    }) as typeof fetch;
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    await generateWithConfirm();
    expect(await screen.findByRole("alert")).toHaveTextContent("Gemini error 503");
    expect(screen.getByRole("button", { name: "Get suggestions" })).toBeEnabled();
  });

  it("says AI is turned off", async () => {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ error: { code: "ai_disabled",
          message: "AI briefs are turned off" } }), { status: 503 });
      }
      return new Response(JSON.stringify(NO_BRIEF.body), { status: 404 });
    }) as typeof fetch;
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    await generateWithConfirm();
    expect(await screen.findByRole("alert")).toHaveTextContent("Suggestions are turned off.");
  });

  it("shows the evidence-is-complete message when the brief endpoint is down", async () => {
    mockApi({ "/opportunities/opp-1/brief": { status: 503, body: { error: { code: "not_ready",
      message: "cannot open app.duckdb" } } } });
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    expect(await screen.findByText(/measured facts and the estimate are complete/))
      .toBeInTheDocument();
  });
});
