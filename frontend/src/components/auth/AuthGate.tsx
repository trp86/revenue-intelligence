// The gate in front of the app (story #191): it asks the API who is signed in and shows the
// login page until someone is. The URL is left alone, so after signing in the user is on the
// page they asked for. Any later 401 (the session expired) brings the login page back.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import { api, isSignedOut } from "../../api/client";
import { LoginPage } from "./LoginPage";

export const ME = ["me"] as const;

export function AuthGate({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const me = useQuery({ queryKey: ME, queryFn: api.me, retry: false, staleTime: Infinity });

  // a data call that answers 401 means the session ended: ask again who is signed in
  useEffect(
    () =>
      client.getQueryCache().subscribe((event) => {
        const { query } = event;
        if (event.type === "updated" && query.queryKey[0] !== ME[0] && isSignedOut(query.state.error)) {
          void client.invalidateQueries({ queryKey: ME });
        }
      }),
    [client],
  );

  if (me.isPending) {
    return (
      <div role="status" aria-live="polite" className="flex min-h-screen items-center justify-center bg-bg">
        <span className="text-sm text-muted">Loading…</span>
      </div>
    );
  }
  if (me.isError || !me.data) {
    const notice = me.isError && !isSignedOut(me.error)
      ? "The app cannot reach its server right now. Try again in a moment."
      : undefined;
    return <LoginPage notice={notice} />;
  }
  return <>{children}</>;
}
