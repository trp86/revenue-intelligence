// The top bar (story #147): the menu button on narrow screens, breadcrumbs, the as-of date, and
// the not-reachable and not-built banners. The net sales field badge was removed in story #161;
// the field is named in the definition of every net sales value (Metric).
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CalendarDays, Menu } from "lucide-react";
import { useState } from "react";

import { api } from "../../api/client";
import { Breadcrumb } from "../ui/breadcrumb";
import { Button } from "../ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../ui/sheet";
import { useCrumbs } from "./crumbs";
import { Brand, NavLinks } from "./Sidebar";

export function TopBar() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const info = health.data;
  const { items } = useCrumbs();
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <header className="sticky top-0 z-topbar border-b border-border bg-surface">
      <div className="flex min-h-14 flex-wrap items-center gap-3 px-4 py-2 md:px-6">
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
              <Menu className="h-5 w-5" aria-hidden="true" />
            </Button>
          </SheetTrigger>
          <SheetContent className="on-dark bg-sidebar text-sidebar-text">
            <SheetTitle className="sr-only">Menu</SheetTitle>
            <SheetDescription className="sr-only">Go to a screen of the app.</SheetDescription>
            <Brand />
            <NavLinks onNavigate={() => setMenuOpen(false)} />
          </SheetContent>
        </Sheet>
        <div className="min-w-0 flex-1">
          <Breadcrumb items={items} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm" aria-live="polite">
          {info?.as_of_date && (
            <span className="inline-flex items-center gap-1 text-muted">
              <CalendarDays className="h-4 w-4" aria-hidden="true" />
              Data as of <strong className="text-text">{info.as_of_date}</strong>
            </span>
          )}
        </div>
      </div>
      {health.isError && (
        <p role="alert" className="flex items-center gap-2 border-t border-danger bg-danger-bg px-4 py-2 text-sm text-danger md:px-6">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          API not reachable. Start it with `uv run revint serve`.
        </p>
      )}
      {info?.status === "not_ready" && (
        <p role="alert" className="flex items-center gap-2 border-t border-warn bg-warn-bg px-4 py-2 text-sm text-warn md:px-6">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          Data not built: {info.message}
        </p>
      )}
    </header>
  );
}
