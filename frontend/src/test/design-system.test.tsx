// Story #146: the design system foundation (tokens, primitives, feedback components).
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AsyncBoundary } from "../components/AsyncBoundary";
import { ConfirmDialog } from "../components/feedback/ConfirmDialog";
import { EmptyState } from "../components/feedback/EmptyState";
import { ErrorState } from "../components/feedback/ErrorState";
import { Badge } from "../components/ui/badge";
import { Breadcrumb } from "../components/ui/breadcrumb";
import { Button } from "../components/ui/button";
import { Toaster, toast } from "../components/ui/toaster";

const TOKENS = readFileSync(join(__dirname, "..", "tokens", "tokens.css"), "utf-8");

function token(name: string): string {
  const match = TOKENS.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`));
  if (!match) throw new Error(`token --color-${name} not found`);
  return match[1];
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("AC1 the token palette", () => {
  it("defines every role of the design system", () => {
    for (const name of ["bg", "surface", "border", "border-strong", "text", "text-muted",
      "sidebar-bg", "sidebar-text", "sidebar-muted", "sidebar-active", "opportunity",
      "opportunity-bg", "measured", "measured-bg", "estimate", "ai", "ai-bg", "warn",
      "warn-bg", "danger", "danger-bg", "focus", "focus-on-dark", "chart-1", "chart-2",
      "chart-3", "chart-4"]) {
      expect(TOKENS).toContain(`--color-${name}:`);
    }
    for (const name of ["--shadow-sm", "--shadow-md", "--radius-lg", "--font-heading",
      "--motion-fast"]) {
      expect(TOKENS).toContain(`${name}:`);
    }
  });

  it.each([
    ["text", "bg"], ["text", "surface"], ["text-muted", "surface"], ["text-muted", "bg"],
    ["sidebar-text", "sidebar-bg"], ["sidebar-active", "sidebar-bg"],
    ["sidebar-muted", "sidebar-bg"], ["opportunity", "surface"],
    ["opportunity", "opportunity-bg"], ["on-primary", "primary"], ["measured", "measured-bg"],
    ["ai", "ai-bg"], ["warn", "warn-bg"], ["danger", "danger-bg"],
  ])("text %s on %s meets WCAG AA (4.5:1)", (fg, bg) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(4.5);
  });

  it.each([
    ["border-strong", "surface"], ["focus", "surface"], ["focus-on-dark", "sidebar-bg"],
    ["chart-1", "surface"], ["chart-2", "surface"], ["chart-3", "surface"],
    ["chart-4", "surface"],
  ])("non-text %s on %s meets 3:1", (fg, bg) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(3);
  });

  it("keeps the token names the existing screens use", () => {
    for (const name of ["primary", "on-primary", "estimate-bg", "success", "priority-high",
      "priority-medium", "priority-low"]) {
      expect(TOKENS).toContain(`--color-${name}:`);
    }
  });
});

describe("AC2 fonts and focus", () => {
  it("bundles Inter and Plus Jakarta Sans locally, with no font CDN", () => {
    const main = readFileSync(join(__dirname, "..", "main.tsx"), "utf-8");
    expect(main).toContain("@fontsource/inter");
    expect(main).toContain("@fontsource/plus-jakarta-sans");
    const html = readFileSync(join(__dirname, "..", "..", "index.html"), "utf-8");
    const css = readFileSync(join(__dirname, "..", "index.css"), "utf-8");
    expect(html + css).not.toMatch(/fonts\.googleapis|fonts\.gstatic/);
  });

  it("draws a 2 px focus ring from the focus token on every element", () => {
    const css = readFileSync(join(__dirname, "..", "index.css"), "utf-8");
    expect(css).toMatch(/:focus-visible\s*{\s*outline: 2px solid var\(--color-focus\)/);
    expect(css).toContain("prefers-reduced-motion");
  });
});

describe("AC3 primitives", () => {
  it("Button is a real button with a type, and supports variants", async () => {
    const onClick = vi.fn();
    render(<><Button onClick={onClick}>Go</Button><Button variant="outline" disabled>Off</Button></>);
    const go = screen.getByRole("button", { name: "Go" });
    expect(go).toHaveAttribute("type", "button");
    await userEvent.click(go);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Off" })).toBeDisabled();
  });

  it("Badge renders its text with the tone classes", () => {
    render(<Badge tone="ai">AI suggestion</Badge>);
    expect(screen.getByText("AI suggestion").className).toContain("text-ai");
  });

  it("Breadcrumb links all but the current page", () => {
    render(
      <MemoryRouter>
        <Breadcrumb items={[{ label: "Overview", to: "/" }, { label: "Opportunities",
          to: "/opportunities" }, { label: "Dormant customer: Shop A" }]} />
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(nav.querySelectorAll("a")).toHaveLength(2);
    expect(screen.getByText("Dormant customer: Shop A")).toHaveAttribute("aria-current", "page");
  });

  it("uses Lucide SVG icons, not Unicode symbols, in the new components", () => {
    render(<ErrorState title="Failed" message="m" onRetry={() => {}} />);
    expect(screen.getByRole("alert").querySelector("svg")).not.toBeNull();
    for (const file of ["feedback/EmptyState.tsx", "feedback/ErrorState.tsx",
      "feedback/ConfirmDialog.tsx", "ui/breadcrumb.tsx", "ui/select.tsx", "ui/dialog.tsx",
      "ui/sheet.tsx"]) {
      const source = readFileSync(join(__dirname, "..", "components", file), "utf-8");
      expect(source, file).not.toMatch(/[▲■▽✔✦≈ⓘ⚠●○]/u);
    }
  });
});

describe("AC4 feedback components", () => {
  it("EmptyState says why and offers an action", () => {
    render(<EmptyState title="No opportunities" reason="No match for these filters."
      action={<Button>Clear filters</Button>} />);
    expect(screen.getByRole("status")).toHaveTextContent("No match for these filters.");
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("ErrorState gives the cause and a Retry", async () => {
    const retry = vi.fn();
    render(<ErrorState title="Could not load" message="The API cannot be reached." onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The API cannot be reached.");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("AsyncBoundary shows a skeleton shaped like the content, marked busy", () => {
    const query = { isPending: true, isError: false, error: null, data: undefined,
      refetch: () => {} };
    const { container } = render(
      <AsyncBoundary query={query} label="opportunities" skeleton="table">{() => null}</AsyncBoundary>,
    );
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(container.querySelector('[data-skeleton="table"]')).not.toBeNull();
  });

  it("ConfirmDialog confirms, cancels with Escape, and returns focus to its trigger", async () => {
    const onConfirm = vi.fn();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <Button onClick={() => setOpen(true)}>Generate brief</Button>
          <ConfirmDialog open={open} onOpenChange={setOpen} title="Generate an AI brief?"
            description="This calls Gemini and counts toward the daily limit."
            confirmLabel="Generate" onConfirm={onConfirm} />
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Generate brief" });
    await userEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Generate an AI brief?" });
    expect(dialog).toHaveTextContent("counts toward the daily limit");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
    await waitFor(() => expect(trigger).toHaveFocus());
    await userEvent.click(trigger);
    await userEvent.click(await screen.findByRole("button", { name: "Generate" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a toast is announced without taking focus", async () => {
    render(<><Button>Stay here</Button><Toaster /></>);
    const button = screen.getByRole("button", { name: "Stay here" });
    button.focus();
    act(() => {
      toast.success("AI brief generated");
    });
    expect(await screen.findByText("AI brief generated")).toBeInTheDocument();
    expect(button).toHaveFocus();
  });
});
