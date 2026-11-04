// The navy sidebar (story #147): app name and the two screens, with icons and labels; the active
// item is shown by a bar, bold text and aria-current, not by colour alone.
import { LayoutDashboard, ListFilter, TrendingUp, type LucideIcon } from "lucide-react";
import { NavLink } from "react-router-dom";

import { cn } from "../../lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  hint?: string;
}

export const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/opportunities", label: "Opportunity Explorer", icon: ListFilter, hint: "Main workspace" },
];

export function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-1 px-3">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "group relative flex min-h-10 items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors duration-fast",
              isActive
                ? "bg-sidebar-active-bg font-semibold text-sidebar-active before:absolute before:inset-y-1 before:left-0 before:w-1 before:rounded-full before:bg-opportunity"
                : "text-sidebar-text hover:bg-sidebar-active-bg hover:text-sidebar-active",
            )
          }
        >
          <item.icon className="h-5 w-5 shrink-0" aria-hidden="true" />
          <span className="flex flex-col">
            {item.label}
            {item.hint && <span className="text-xs font-normal text-sidebar-muted">{item.hint}</span>}
          </span>
        </NavLink>
      ))}
    </nav>
  );
}

export function Brand() {
  return (
    <div className="flex items-center gap-2 px-6 py-5">
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-opportunity text-on-primary">
        <TrendingUp className="h-5 w-5" aria-hidden="true" />
      </span>
      <span className="font-heading text-base font-bold text-sidebar-active">Revenue Intelligence</span>
    </div>
  );
}

/** The fixed sidebar for wide screens (768 px and up). */
export function Sidebar() {
  return (
    <aside className="on-dark fixed inset-y-0 left-0 z-topbar hidden w-64 flex-col bg-sidebar md:flex">
      <Brand />
      <NavLinks />
      <p className="mt-auto px-6 py-4 text-xs text-sidebar-muted">
        Values are labelled Measured, Estimate or AI suggestion.
      </p>
    </aside>
  );
}
