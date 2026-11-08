// Story #185: short, plain confirmation dialogs.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AiBriefBlock } from "../components/AiBrief";
import { renderWithProviders } from "./render";

const TECHNICAL = /Gemini|daily limit|checks|codes|measured facts of this opportunity/;

const BRIEF = {
  kind: "ai", opp_id: "opp-1",
  brief: { headline: "Win back the customer", explanation: "Quiet.", recommendation: "Call.", actions: [],
    risks: [], confidence_label: "Medium", evidence_ids_used: [] },
  provenance: { model: "gemini-2.5-flash", prompt_version: "system.v2+dormancy.v1@abc",
    generated_at: "2026-11-08T09:00:00", validation_status: "valid", review_status: "Draft", cached: false },
};

function api(hasBrief: boolean) {
  const posts: string[] = [];
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") posts.push("post");
    return hasBrief || init?.method === "POST"
      ? new Response(JSON.stringify(BRIEF))
      : new Response(JSON.stringify({ error: { code: "no_brief", message: "none" } }), { status: 404 });
  }) as typeof fetch;
  return posts;
}

describe("story #185 simple dialogs", () => {
  it("AC1 AC3 'Get suggestions?' is short and plain", async () => {
    const posts = api(false);
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Get suggestions" }));
    const dialog = await screen.findByRole("dialog", { name: "Get suggestions?" });
    expect(dialog).toHaveTextContent(
      "We'll suggest next steps based on the facts on this page. Customer names are never shared.");
    expect(dialog).not.toHaveTextContent(TECHNICAL);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Get suggestions" })).toBeInTheDocument();
    expect(posts).toHaveLength(0);
  });

  it("AC2 AC3 'Refresh suggestions?' is short and plain", async () => {
    api(true);
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    await screen.findByText("Win back the customer");
    await userEvent.click(screen.getByRole("button", { name: "Refresh suggestions" }));
    const dialog = await screen.findByRole("dialog", { name: "Refresh suggestions?" });
    expect(dialog).toHaveTextContent(
      "We'll replace these suggestions with new ones. The current ones are kept in the history.");
    expect(dialog).not.toHaveTextContent(TECHNICAL);
    expect(within(dialog).getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });

  it("AC4 Cancel still sends nothing", async () => {
    const posts = api(false);
    renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Get suggestions" }));
    const dialog = await screen.findByRole("dialog", { name: "Get suggestions?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts).toHaveLength(0);
  });
});
