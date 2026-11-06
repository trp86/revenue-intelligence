// Story #162: a definition popup is never clipped by a scroll container and stays on screen.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DefinitionButton } from "../components/Metric";
import { mockApi, renderWithProviders } from "./render";

const DEFINITIONS = {
  definitions: [{ id: "opp_value_high", group: "column", text: "Estimated value, high end of the range." }],
};

function place(button: HTMLElement, rect: Partial<DOMRect>) {
  button.getBoundingClientRect = () =>
    ({ top: 0, bottom: 0, left: 0, right: 0, width: 24, height: 24, x: 0, y: 0, ...rect }) as DOMRect;
}

function scrollingTable() {
  return renderWithProviders(
    <div data-testid="scroller" style={{ overflowX: "auto" }}>
      <DefinitionButton definitionId="opp_value_high" label="value (estimate)" unit="net sales" />
    </div>,
  );
}

describe("AC1 the popup is not clipped and stays on screen", () => {
  it("renders outside the scroll container, on the document body", async () => {
    mockApi({ "/definitions": DEFINITIONS, "/health": { status: "ready" } });
    scrollingTable();
    await userEvent.click(screen.getByRole("button", { name: "Definition of value (estimate)" }));
    const tip = await screen.findByRole("tooltip");
    expect(screen.getByTestId("scroller").contains(tip)).toBe(false);
    expect(tip.parentElement).toBe(document.body); // no <main> in this test; in the app it is <main>
    expect(tip).toHaveTextContent("Estimated value, high end of the range.");
  });

  it("shifts left to stay inside the viewport when the button is at the right edge", async () => {
    mockApi({ "/definitions": DEFINITIONS, "/health": { status: "ready" } });
    scrollingTable();
    const button = screen.getByRole("button", { name: "Definition of value (estimate)" });
    place(button, { left: window.innerWidth - 20, right: window.innerWidth - 4, top: 100, bottom: 124 });
    await userEvent.click(button);
    const tip = await screen.findByRole("tooltip");
    const left = parseFloat(tip.style.left);
    const width = parseFloat(tip.style.width);
    expect(width).toBeGreaterThanOrEqual(240);
    expect(left).toBeGreaterThanOrEqual(8);
    expect(left + width).toBeLessThanOrEqual(window.innerWidth - 8);
  });

  it("flips above the button when there is no room below", async () => {
    mockApi({ "/definitions": DEFINITIONS, "/health": { status: "ready" } });
    scrollingTable();
    const button = screen.getByRole("button", { name: "Definition of value (estimate)" });
    place(button, { left: 100, right: 124, top: window.innerHeight - 30, bottom: window.innerHeight - 6 });
    await userEvent.click(button);
    const tip = await screen.findByRole("tooltip");
    expect(tip.style.bottom).not.toBe("");
    expect(tip.style.top).toBe("");
  });
});

describe("AC2 it sits above the content", () => {
  it("uses the dialog z-index token and a fixed position", async () => {
    mockApi({ "/definitions": DEFINITIONS, "/health": { status: "ready" } });
    scrollingTable();
    await userEvent.click(screen.getByRole("button", { name: "Definition of value (estimate)" }));
    const tip = await screen.findByRole("tooltip");
    expect(tip.className).toContain("z-dialog");
    expect(tip.className).toContain("fixed");
  });
});

describe("AC3 keyboard behaviour is unchanged", () => {
  it("Enter opens it, Escape closes it and focus stays on the button", async () => {
    mockApi({ "/definitions": DEFINITIONS, "/health": { status: "ready" } });
    scrollingTable();
    const button = screen.getByRole("button", { name: "Definition of value (estimate)" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
});

describe("story #173 one popup at a time", () => {
  function two() {
    mockApi({ "/definitions": DEFINITIONS, "/health": { status: "ready" } });
    return renderWithProviders(
      <div>
        <DefinitionButton definitionId="opp_value_high" label="first" />
        <DefinitionButton definitionId="opp_value_high" label="second" />
        <p>outside</p>
      </div>,
    );
  }

  it("AC1 opening a second popup closes the first", async () => {
    two();
    await userEvent.click(screen.getByRole("button", { name: "Definition of first" }));
    await userEvent.click(screen.getByRole("button", { name: "Definition of second" }));
    expect(await screen.findAllByRole("tooltip")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Definition of first" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Definition of second" })).toHaveAttribute("aria-expanded", "true");
  });

  it("AC2 a click outside closes it", async () => {
    two();
    await userEvent.click(screen.getByRole("button", { name: "Definition of first" }));
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    await userEvent.click(screen.getByText("outside"));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("AC2 a click inside the popup keeps it open", async () => {
    two();
    await userEvent.click(screen.getByRole("button", { name: "Definition of first" }));
    await userEvent.click(await screen.findByRole("tooltip"));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });
});
