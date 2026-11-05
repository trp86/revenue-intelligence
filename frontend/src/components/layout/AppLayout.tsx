// The app layout (story #147): a skip link, the navy sidebar (a Sheet below 768 px), the top bar
// and the main region. On a route change focus moves to the main region, so keyboard and
// screen reader users start on the new page.
import { useEffect, useRef, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { CrumbProvider } from "./crumbs";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

function MainRegion({ children }: { children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  // the previous path, not a "first render" flag: StrictMode runs effects twice in development,
  // which would otherwise move focus past the skip link on the first page load (story #151)
  const previous = useRef(pathname);
  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    main.current?.focus();
  }, [pathname]);
  return (
    <main id="main" ref={main} tabIndex={-1} className="mx-auto w-full max-w-7xl px-4 py-6 outline-none md:px-6 md:py-8">
      {children}
    </main>
  );
}

export function AppLayout({ children }: { children: ReactNode }) {
  return (
    <CrumbProvider>
      <div className="min-h-dvh bg-bg text-text">
        <a
          href="#main"
          className="sr-only z-toast rounded-md bg-surface px-4 py-2 text-sm font-medium text-text shadow-md focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
        >
          Skip to main content
        </a>
        <Sidebar />
        <div className="flex min-h-dvh flex-col md:pl-64">
          <TopBar />
          <MainRegion>{children}</MainRegion>
        </div>
      </div>
    </CrumbProvider>
  );
}
