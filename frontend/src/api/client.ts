// The only module that calls the network (spec 07 section 11, story #135). Screens use the
// typed functions below through TanStack Query; they never call fetch, DuckDB or Gemini.
import type {
  BriefResponse,
  Definition,
  Health,
  OpportunitiesPage,
  OpportunityDetail,
  OpportunityFilters,
  Overview,
} from "./types";

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function get<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  method: "GET" | "POST" = "GET",
  json?: unknown,
) {
  const url = new URL(API_BASE + path);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
  }
  let response: Response;
  try {
    // credentials: "include" sends the session cookie with every call (story #191)
    response = await fetch(url, {
      method,
      credentials: "include",
      headers: json === undefined
        ? { Accept: "application/json" }
        : { Accept: "application/json", "Content-Type": "application/json" },
      body: json === undefined ? undefined : JSON.stringify(json),
    });
  } catch {
    throw new ApiError(0, "network", "The API cannot be reached. Is `revint serve` running?");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = body?.error ?? {};
    throw new ApiError(response.status, error.code ?? "error", error.message ?? response.statusText);
  }
  return body as T;
}

/** A 401 from the API: nobody is signed in, or the session has ended (story #191). */
export function isSignedOut(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export const api = {
  health: () => get<Health>("/health"),
  me: () => get<{ user: string }>("/auth/me"),
  login: (username: string, password: string) =>
    get<{ user: string }>("/auth/login", undefined, "POST", { username, password }),
  logout: () => get<{ ok: boolean }>("/auth/logout", undefined, "POST"),
  definitions: () => get<{ definitions: Definition[] }>("/definitions"),
  overview: () => get<Overview>("/overview"),
  opportunities: (filters: OpportunityFilters) =>
    get<OpportunitiesPage>("/opportunities", { ...filters }),
  opportunity: (id: string) => get<OpportunityDetail>(`/opportunities/${encodeURIComponent(id)}`),
  brief: (id: string) => get<BriefResponse>(`/opportunities/${encodeURIComponent(id)}/brief`),
  /** `regenerate` skips the cache and always calls Gemini (story #181). */
  generateBrief: (id: string, regenerate = false) =>
    get<BriefResponse>(`/opportunities/${encodeURIComponent(id)}/brief`,
      regenerate ? { regenerate: "true" } : undefined, "POST"),
};
