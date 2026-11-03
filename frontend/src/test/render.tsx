// Render a component with the providers the app uses, and a mocked API.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { DefinitionsProvider } from "../components/Definitions";

export function renderWithProviders(ui: ReactNode, route = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DefinitionsProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </DefinitionsProvider>
    </QueryClientProvider>,
  );
}

/** Replace fetch with a router of path -> body (or a status and error). */
export function mockApi(routes: Record<string, unknown | { status: number; body: unknown }>) {
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    calls.push(url.pathname + url.search);
    const key = Object.keys(routes).find((path) => url.pathname.endsWith(path));
    if (key === undefined) return new Response(JSON.stringify({ error: { code: "not_found",
      message: "no route" } }), { status: 404 });
    const value = routes[key] as { status?: number; body?: unknown };
    if (value && typeof value === "object" && "status" in value && "body" in value) {
      return new Response(JSON.stringify(value.body), { status: value.status });
    }
    return new Response(JSON.stringify(routes[key]), { status: 200 });
  }) as typeof fetch;
  return calls;
}
