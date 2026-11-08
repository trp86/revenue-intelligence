// Story #181: regenerate the AI suggestion from the Detail page.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AiBriefBlock } from "../components/AiBrief";
import { Toaster } from "../components/ui/toaster";
import { renderWithProviders } from "./render";

const brief = (headline: string) => ({
  kind: "ai", opp_id: "opp-1",
  brief: { headline, explanation: "It has gone quiet.", recommendation: "Call this week.", actions: [],
    risks: [], confidence_label: "Medium", evidence_ids_used: [] },
  provenance: { model: "gemini-2.5-flash", prompt_version: "system.v2+dormancy.v1@abc",
    generated_at: "2026-11-08T09:00:00", validation_status: "valid", review_status: "Draft", cached: false },
});

function api({ fail = false } = {}) {
  const posts: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    if (init?.method === "POST") {
      posts.push(url.search);
      return fail ? json({ error: { code: "ai_unavailable", message: "Gemini error 503" } }, 503)
        : json(brief("A fresh suggestion"));
    }
    return json(brief("The old suggestion"));
  }) as typeof fetch;
  return posts;
}

function page() {
  renderWithProviders(<><AiBriefBlock oppId="opp-1" /><Toaster /></>);
}

async function openRegenerate() {
  await screen.findByText("The old suggestion");
  await userEvent.click(screen.getByText("About this suggestion"));
  await userEvent.click(screen.getByRole("button", { name: "Refresh suggestions" }));
  return screen.findByRole("dialog", { name: "Refresh the suggestions?" });
}

describe("story #181 regenerate", () => {
  it("AC1 a brief has a Regenerate button inside 'About this suggestion'", async () => {
    api();
    page();
    await screen.findByText("The old suggestion");
    const details = screen.getByText("About this suggestion").closest("details")!;
    expect(within(details).getByRole("button", { name: "Refresh suggestions" })).toBeInTheDocument();
  });

  it("AC2 AC3 confirming asks for a fresh brief, shows it and a toast", async () => {
    const posts = api();
    page();
    const dialog = await openRegenerate();
    expect(dialog).toHaveTextContent("counts toward the daily limit");
    expect(posts).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Refresh suggestions" }));
    expect(await screen.findByText("A fresh suggestion")).toBeInTheDocument();
    expect(await screen.findByText("New suggestions ready")).toBeInTheDocument();
    expect(posts).toEqual(["?regenerate=true"]);
  });

  it("AC2 cancelling sends nothing", async () => {
    const posts = api();
    page();
    const dialog = await openRegenerate();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts).toHaveLength(0);
  });

  it("AC4 a failure shows an error toast and keeps the previous brief", async () => {
    api({ fail: true });
    page();
    const dialog = await openRegenerate();
    await userEvent.click(within(dialog).getByRole("button", { name: "Refresh suggestions" }));
    expect(await screen.findByText(/could not be created; the current ones are kept/)).toBeInTheDocument();
    expect(screen.getByText("The old suggestion")).toBeInTheDocument();
  });
});
