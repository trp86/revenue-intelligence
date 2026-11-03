// The persistent shell (spec 07 section 3): navigation and a header with the as-of date and the
// net sales label from /health.
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { api } from "../api/client";

const NAV = [
  { to: "/", label: "Overview" },
  { to: "/opportunities", label: "Opportunities" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const info = health.data;
  return (
    <div className="min-h-screen bg-bg text-text">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-3">
        <div className="flex items-center gap-6">
          <span className="text-lg font-semibold">Revenue Intelligence</span>
          <nav aria-label="Main">
            <ul className="flex gap-4">
              {NAV.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      `px-1 py-1 ${isActive ? "border-b-2 border-primary font-semibold text-primary" : "text-muted"}`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </div>
        <div className="flex flex-wrap gap-3 text-sm" aria-live="polite">
          {health.isError && <span className="text-danger">âš  API not reachable</span>}
          {info?.status === "not_ready" && (
            <span className="text-warn">âš  Data not built: {info.message}</span>
          )}
          {info?.as_of_date && (
            <span>
              Data as of <strong>{info.as_of_date}</strong>
            </span>
          )}
          {info && (
            <span className="rounded border border-border px-2">
              Net sales: {info.net_sales_field}
              {info.net_sales_provisional ? " (provisional)" : ""}
            </span>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl p-6">{children}</main>
    </div>
  );
}
