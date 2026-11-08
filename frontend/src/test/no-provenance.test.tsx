// Story #189: the suggestion block shows no technical provenance; Refresh stays.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AiBriefBlock } from "../components/AiBrief";
import { renderWithProviders } from "./render";

const BRIEF = {
  kind: "ai", opp_id: "opp-1",
  brief: { headline: "Win back the customer", explanation: "Quiet.", recommendation: "Call.", actions: [],
    risks: [], confidence_label: "High", evidence_ids_used: [] },
  provenance: { model: "gemini-2.5-flash", prompt_version: "system.v2+dormancy.v1@abc",
    generated_at: "2026-11-08T21:13:00", validation_status: "valid", review_status: "Draft", cached: false },
};

describe("story #189 no provenance line", () => {
  it("AC1 no model, prompt, time, review status or confidence text, and no 'About this suggestion'", async () => {
    globalThis.fetch = (async () => new Response(JSON.stringify(BRIEF))) as typeof fetch;
    const { container } = renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    await screen.findByText("Win back the customer");
    for (const text of ["gemini", "system.v2", "2026-11-08", "Draft", "confidence", "About this suggestion",
      "Written by AI"]) {
      expect(container.textContent?.toLowerCase()).not.toContain(text.toLowerCase());
    }
    expect(container.querySelector("details")).toBeNull();
  });

  it("AC2 the Refresh suggestions button stays, visible without opening anything", async () => {
    globalThis.fetch = (async () => new Response(JSON.stringify(BRIEF))) as typeof fetch;
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    await screen.findByText("Win back the customer");
    expect(screen.getByRole("button", { name: "Refresh suggestions" })).toBeVisible();
  });
});
