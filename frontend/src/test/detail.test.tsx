// Story #150: the Opportunity Detail, with a clear hierarchy and separated evidence and AI.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Toaster } from "../components/ui/toaster";
import { Detail } from "../screens/Detail";
import { DEFINITIONS, DETAIL } from "./fixtures";
import { renderWithProviders } from "./render";

const BRIEF = {
  kind: "ai", opp_id: "opp-1",
  brief: { headline: "Win back a quiet customer", explanation: "It has gone quiet.",
    recommendation: "Call this week.", actions: [{ text: "Call the buyer",
      suggested_owner_role: "Sales rep", evidence_ids: [] }], risks: [], confidence_label: "Medium",
    evidence_ids_used: [] },
  provenance: { model: "gemini-2.5-flash", prompt_version: "system.v1+dormancy.v1@abc",
    generated_at: "2026-11-05T09:00:00", validation_status: "valid", review_status: "Draft", cached: false },
};

/** The API for the Detail page: the opportunity, its brief (404 until generated), definitions. */
function api({ generate = "ok" as "ok" | "fail" } = {}) {
  let generated = false;
  const posts: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    if (path.endsWith("/definitions")) return json(DEFINITIONS);
    if (path.endsWith("/brief") && init?.method === "POST") {
      posts.push(path);
      if (generate === "fail") {
        return json({ error: { code: "ai_unavailable", message: "Gemini error 503" } }, 503);
      }
      generated = true;
      return json(BRIEF);
    }
    if (path.endsWith("/brief")) {
      return generated ? json(BRIEF)
        : json({ error: { code: "no_brief", message: "no brief yet" } }, 404);
    }
    if (path.endsWith("/opportunities/opp-1")) return json(DETAIL);
    return json({ error: { code: "not_found", message: "no opportunity with that id" } }, 404);
  }) as typeof fetch;
  return posts;
}

function page(route = "/opportunities/opp-1") {
  return renderWithProviders(
    <>
      <Routes><Route path="/opportunities/:id" element={<Detail />} /></Routes>
      <Toaster />
    </>,
    route,
  );
}

describe("AC1 the header: what happened, where, why it matters", () => {
  it("shows the type, customer, place, priority, confidence, score and what happened", async () => {
    api();
    page();
    expect(await screen.findByRole("heading", { level: 1, name: "Shop 1 · C1" })).toBeInTheDocument();
    expect(screen.getAllByText("Dormant customer")[0]).toBeInTheDocument();
    expect(screen.getByText(/Branch: Magway · Channel: GT · Category: Whole customer/)).toBeInTheDocument();
    const why = screen.getByLabelText("Why it matters");
    expect(within(why).getByText("Priority")).toBeInTheDocument();
    expect(within(why).getByText("High")).toBeInTheDocument(); // the priority pill
    expect(within(why).getByText("Medium")).toBeInTheDocument(); // the confidence
    expect(within(why).getByText("89")).toBeInTheDocument(); // the score
    expect(screen.getByText("No order for 100 days; this customer usually orders every 30 days."))
      .toBeInTheDocument();
  });
});

describe("AC2 separate Measured, Estimate and AI blocks", () => {
  it("shows each block with its own heading and icon", async () => {
    api();
    page();
    const measured = await screen.findByRole("region", { name: "Measured fact" });
    const estimate = screen.getByRole("region", { name: "Estimate" });
    const ai = screen.getByRole("region", { name: "Suggested next steps (AI-generated)" });
    for (const block of [measured, estimate, ai]) {
      expect(within(block).getByRole("heading", { level: 2 }).previousElementSibling?.tagName).toBe("svg");
    }
    expect(within(measured).getByText("Days since the last order")).toBeInTheDocument();
    expect(within(measured).getByRole("button", { name: "Definition of Days since the last order" }))
      .toBeInTheDocument();
    // plain text since story #171 (the "Not a measured result" note was removed)
    expect(within(estimate).getByText(/^Based on 25% to 75% of what this customer bought/)).toBeInTheDocument();
    expect(ai).not.toHaveTextContent("Gemini"); // story #170
    expect(within(ai).getByText("(AI-generated)")).toHaveClass("sr-only");
    // the blocks are siblings, never nested: evidence and AI output stay apart
    expect(measured.contains(ai) || ai.contains(measured)).toBe(false);
  });
});

describe("AC3 Generate brief asks first and reports the result", () => {
  it("confirms, generates and shows a success toast and the brief", async () => {
    const posts = api();
    page();
    const ai = await screen.findByRole("region", { name: /Suggested next steps/ });
    await userEvent.click(await within(ai).findByRole("button", { name: "Generate brief" }));
    const dialog = await screen.findByRole("dialog", { name: "Generate an AI brief?" });
    expect(dialog).toHaveTextContent("counts toward the daily limit");
    expect(dialog).toHaveTextContent("never customer names or codes");
    expect(posts).toHaveLength(0); // nothing is sent before confirming
    await userEvent.click(within(dialog).getByRole("button", { name: "Generate" }));
    expect(await screen.findByText("AI brief generated")).toBeInTheDocument();
    expect(await within(ai).findByText("Win back a quiet customer")).toBeInTheDocument();
    expect(posts).toHaveLength(1);
  });

  it("cancelling sends nothing", async () => {
    const posts = api();
    page();
    const ai = await screen.findByRole("region", { name: /Suggested next steps/ });
    await userEvent.click(await within(ai).findByRole("button", { name: "Generate brief" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts).toHaveLength(0);
  });

  it("a failure shows an error toast and the reason, and keeps the evidence", async () => {
    api({ generate: "fail" });
    page();
    const ai = await screen.findByRole("region", { name: /Suggested next steps/ });
    await userEvent.click(await within(ai).findByRole("button", { name: "Generate brief" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Generate" }));
    expect(await screen.findByText("The AI brief could not be generated")).toBeInTheDocument();
    expect(await within(ai).findByRole("alert")).toHaveTextContent("Gemini error 503");
    expect(screen.getByRole("region", { name: "Measured fact" })).toBeInTheDocument();
  });
});

describe("AC4 reasons and data-quality notes", () => {
  it("shows reason chips and the notes", async () => {
    api();
    page();
    const reasons = await screen.findByRole("list", { name: "Reasons" });
    expect(within(reasons).getByText("confidence capped")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Data quality notes" }))
      .getByText(/may stand for more than one customer/)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("multiple spellings");
  });
});

describe("AC5 loading and error", () => {
  it("shows a detail skeleton, then the page", async () => {
    api();
    const { container } = page();
    expect(container.querySelector('[data-skeleton="detail"]')).not.toBeNull();
    expect(await screen.findByRole("region", { name: "Measured fact" })).toBeInTheDocument();
  });

  it("an unknown id shows an error with Retry", async () => {
    api();
    page("/opportunities/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load this opportunity");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("has no axe violations (contrast is checked in the browser)", async () => {
    api();
    const { container } = page();
    await screen.findByRole("region", { name: "Measured fact" });
    const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
