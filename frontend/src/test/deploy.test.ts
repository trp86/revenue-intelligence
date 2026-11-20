// Story #193: a relative API base behind the Netlify proxy, and the forwarding rules.
import { describe, expect, it } from "vitest";

import { apiUrl } from "../api/client";
// @ts-expect-error a plain .mjs script, no types
import { apiOrigin, redirects } from "../../scripts/netlify.mjs";

describe("AC3 the API address", () => {
  it("a relative base resolves against the page's own address", () => {
    expect(apiUrl("/api/v1", "/overview", "https://revint.netlify.app").href)
      .toBe("https://revint.netlify.app/api/v1/overview");
  });

  it("the local absolute default is unchanged", () => {
    expect(apiUrl("http://localhost:8000/api/v1", "/health", "http://localhost:5173").href)
      .toBe("http://localhost:8000/api/v1/health");
  });
});

describe("AC4 the Netlify forwarding rules", () => {
  it("proxy /api/* to Railway first, then serve the app for every other path", () => {
    expect(redirects("https://revint-api.up.railway.app")).toBe(
      "/api/*  https://revint-api.up.railway.app/api/:splat  200\n/*      /index.html  200\n");
  });

  it("refuse an address that is not plain https", () => {
    expect(() => apiOrigin("http://revint-api.up.railway.app")).toThrow(/https/);
    expect(() => apiOrigin("https://revint-api.up.railway.app/api/v1")).toThrow(/without a path/);
    expect(() => apiOrigin("")).toThrow(/Railway address/);
    expect(apiOrigin(" https://revint-api.up.railway.app/ ")).toBe("https://revint-api.up.railway.app");
  });
});
