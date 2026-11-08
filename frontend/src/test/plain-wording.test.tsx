// Story #183: plain wording for the suggestion block; no sidebar note.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AiBriefBlock } from "../components/AiBrief";
import { Toaster } from "../components/ui/toaster";
import { mockApi, renderWithProviders } from "./render";

const NO_BRIEF = { error: { code: "no_brief", message: "no brief yet" } };

describe("story #183 plain wording", () => {
  it("AC1 the empty block reads plainly, with no 'AI brief' or 'Generate'", async () => {
    globalThis.fetch = (async () => new Response(JSON.stringify(NO_BRIEF), { status: 404 })) as typeof fetch;
    const { container } = renderWithProviders(<AiBriefBlock oppId="opp-1" />);
    expect(await screen.findByText("No suggestions yet for this customer.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get suggestions" })).toBeInTheDocument();
    expect(container).not.toHaveTextContent(/AI brief|Generate/);
  });

  it("AC2 the dialog asks plainly and still says what is sent and that it counts", async () => {
    globalThis.fetch = (async () => new Response(JSON.stringify(NO_BRIEF), { status: 404 })) as typeof fetch;
    renderWithProviders(<><AiBriefBlock oppId="opp-1" /><Toaster /></>);
    await userEvent.click(await screen.findByRole("button", { name: "Get suggestions" }));
    const dialog = await screen.findByRole("dialog", { name: "Get suggestions?" });
    expect(dialog).toHaveTextContent("Customer names are never shared."); // shorter since story #185
    expect(within(dialog).getByRole("button", { name: "Get suggestions" })).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent(/AI brief|Generate/);
  });

  it("AC3 no message in the block's code uses the old wording", () => {
    const source = readFileSync(join(__dirname, "..", "components", "AiBrief.tsx"), "utf-8");
    const strings = [...source.matchAll(/"([^"]*)"/g)].map((m) => m[1]);
    expect(strings.filter((s) => /AI brief|Generate brief|Regenerate the/.test(s))).toEqual([]);
  });

  it("AC4 the sidebar has no 'shown apart' note", () => {
    const sidebar = readFileSync(join(__dirname, "..", "components", "layout", "Sidebar.tsx"), "utf-8");
    expect(sidebar).not.toContain("shown apart");
    mockApi({});
  });
});
