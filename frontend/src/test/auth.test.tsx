// Story #191: the login page, the gate in front of the app, and signing out.
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { api } from "../api/client";
import { AuthGate } from "../components/auth/AuthGate";
import { SignOutButton } from "../components/auth/SignOutButton";

interface Call { path: string; method: string; body: unknown; credentials?: RequestCredentials }

/** A fake API with one user (anna / the right password) and a session that can expire. */
function fakeApi({ signedIn = false } = {}) {
  const state = { signedIn };
  const calls: Call[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ path, method, body, credentials: init?.credentials });
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
    const unauthorised = () => json({ error: { code: "not_signed_in", message: "sign in" } }, 401);
    if (path.endsWith("/auth/login")) {
      if (body.password !== "the right password") {
        return json({ error: { code: "bad_credentials", message: "User name or password is incorrect." } }, 401);
      }
      state.signedIn = true;
      return json({ user: body.username });
    }
    if (path.endsWith("/auth/logout")) {
      state.signedIn = false;
      return json({ ok: true });
    }
    if (!state.signedIn) return unauthorised();
    if (path.endsWith("/auth/me")) return json({ user: "anna" });
    return json({ definitions: [] });
  }) as typeof fetch;
  return { calls, state };
}

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

/** A protected screen that loads data, like the real ones. */
function Screen() {
  const query = useQuery({ queryKey: ["defs"], queryFn: api.definitions });
  return <p>{query.isSuccess ? "The app is open" : "loading"}</p>;
}

function app(route = "/opportunities", client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <AuthGate>
          <SignOutButton />
          <Routes><Route path="*" element={<><Screen /><Where /></>} /></Routes>
        </AuthGate>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function signIn(password = "the right password") {
  await userEvent.type(await screen.findByLabelText("User name"), "anna");
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("AC1 the login page", () => {
  it("shows instead of the app when nobody is signed in", async () => {
    fakeApi();
    app();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("User name")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.queryByText("The app is open")).not.toBeInTheDocument();
  });

  it("says plainly when the user name or password is wrong", async () => {
    fakeApi();
    app();
    await signIn("a wrong password");
    expect(await screen.findByRole("alert")).toHaveTextContent("User name or password is incorrect.");
  });

  it("opens the page that was asked for after signing in", async () => {
    fakeApi();
    app("/opportunities/opp-7");
    await signIn();
    expect(await screen.findByText("The app is open")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/opportunities/opp-7");
  });

  it("has no axe violations (contrast is checked in the browser)", async () => {
    fakeApi();
    const { container } = app();
    await screen.findByRole("heading", { name: "Sign in" });
    const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

describe("AC4 sessions", () => {
  it("every API call sends the session cookie (credentials: include)", async () => {
    const { calls } = fakeApi({ signedIn: true });
    app();
    await screen.findByText("The app is open");
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.every((c) => c.credentials === "include")).toBe(true);
  });

  it("an expired session brings back the login page", async () => {
    const { state } = fakeApi({ signedIn: true });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    app("/", client);
    await screen.findByText("The app is open");
    state.signedIn = false; // the session expires on the server
    await client.invalidateQueries({ queryKey: ["defs"] }); // the next data call answers 401
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("Sign out ends the session and shows the login page", async () => {
    const { calls } = fakeApi({ signedIn: true });
    app();
    await screen.findByText("The app is open");
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/auth/logout"))).toBe(true));
  });
});
