// "Sign out" in the top bar (story #191): ends the session on the server, forgets every loaded
// answer, and the gate shows the login page again.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useState } from "react";

import { api } from "../../api/client";
import { Button } from "../ui/button";

export function SignOutButton() {
  const client = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false, staleTime: Infinity });
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await api.logout();
    } catch {
      // the gate still asks the server below; a failed call leaves nobody signed in on screen
    } finally {
      client.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      await client.invalidateQueries({ queryKey: ["me"] });
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2 text-sm">
      {me.data && <span className="hidden text-muted sm:inline">{me.data.user}</span>}
      <Button variant="outline" size="sm" onClick={() => void signOut()} disabled={busy} aria-busy={busy}>
        <LogOut className="h-4 w-4" aria-hidden="true" />
        Sign out
      </Button>
    </span>
  );
}
