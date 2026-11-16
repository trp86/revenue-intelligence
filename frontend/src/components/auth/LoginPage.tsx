// The login page (story #191): user name, password and "Sign in", in the app's design tokens.
// The password only ever goes to the API's /auth/login; the session is an HttpOnly cookie the
// page cannot read, so nothing is kept in localStorage.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, LogIn, TrendingUp } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError, api } from "../../api/client";
import { Button } from "../ui/button";
import { Input } from "../ui/input";

export function LoginPage({ notice }: { notice?: string }) {
  const client = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.login(username.trim(), password),
    onSuccess: (data) => {
      setPassword("");
      client.setQueryData(["me"], data);
      // anything fetched before signing in was refused: fetch it again
      void client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  });
  const error = login.error instanceof ApiError
    ? login.error.status === 0 ? "The app cannot reach its server right now. Try again in a moment."
      : login.error.message
    : login.error ? "Signing in did not work. Try again." : undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (username.trim() && password) login.mutate();
  }

  return (
    <main id="main" className="flex min-h-screen items-center justify-center bg-bg px-4 py-10">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-6 shadow-md md:p-8">
        <div className="mb-6 flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-opportunity text-on-primary">
            <TrendingUp className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className="font-heading text-base font-bold text-text">Revenue Intelligence</span>
        </div>
        <h1 className="font-heading text-2xl font-bold text-text">Sign in</h1>
        <p className="mt-1 text-sm text-muted">Use the user name and password you were given.</p>
        <form className="mt-6 space-y-4" onSubmit={submit} noValidate>
          <div className="space-y-1">
            <label htmlFor="login-username" className="text-sm font-medium text-text">User name</label>
            <Input id="login-username" name="username" autoComplete="username" autoCapitalize="none"
              spellCheck={false} required value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div className="space-y-1">
            <label htmlFor="login-password" className="text-sm font-medium text-text">Password</label>
            <Input id="login-password" name="password" type="password" autoComplete="current-password" required
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {(error ?? notice) && (
            <p role="alert" className="flex items-start gap-2 rounded-md border border-danger bg-danger-bg p-3 text-sm text-danger">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {error ?? notice}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={login.isPending} aria-busy={login.isPending}>
            <LogIn className="h-4 w-4" aria-hidden="true" />
            {login.isPending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </main>
  );
}
