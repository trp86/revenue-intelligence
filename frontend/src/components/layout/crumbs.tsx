// The breadcrumb trail of the current page (story #147). The trail comes from the route; a page
// whose last crumb needs data (the Detail page: "<Type>: <Customer>") sets it with useCrumbTitle.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import type { Crumb } from "../ui/breadcrumb";

const CrumbTitle = createContext<{ title: string | null; setTitle: (t: string | null) => void }>({
  title: null,
  setTitle: () => {},
});

export function CrumbProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState<string | null>(null);
  return <CrumbTitle.Provider value={{ title, setTitle }}>{children}</CrumbTitle.Provider>;
}

/** Set the last crumb of the current page while it is shown. */
export function useCrumbTitle(title: string | null | undefined) {
  const { setTitle } = useContext(CrumbTitle);
  useEffect(() => {
    setTitle(title ?? null);
    return () => setTitle(null);
  }, [title, setTitle]);
}

export const PAGE_TITLES: Record<string, string> = {
  "/": "Overview",
  "/opportunities": "Opportunity Explorer",
};

/** The trail and the page title for the current route. */
export function useCrumbs(): { items: Crumb[]; pageTitle: string } {
  const { pathname } = useLocation();
  const { title } = useContext(CrumbTitle);
  if (pathname === "/") return { items: [{ label: "Overview" }], pageTitle: "Overview" };
  if (pathname === "/opportunities") {
    return {
      items: [{ label: "Overview", to: "/" }, { label: "Opportunities" }],
      pageTitle: "Opportunity Explorer",
    };
  }
  if (pathname.startsWith("/opportunities/")) {
    const last = title ?? "Opportunity";
    return {
      items: [
        { label: "Overview", to: "/" },
        { label: "Opportunities", to: "/opportunities" },
        { label: last },
      ],
      pageTitle: last,
    };
  }
  return { items: [{ label: "Overview", to: "/" }, { label: "Page not found" }],
    pageTitle: "Page not found" };
}
