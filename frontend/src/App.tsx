import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { isSignedOut } from "./api/client";
import { AuthGate } from "./components/auth/AuthGate";
import { DefinitionsProvider } from "./components/Definitions";
import { AppLayout } from "./components/layout/AppLayout";
import { Toaster } from "./components/ui/toaster";
import { TooltipProvider } from "./components/ui/tooltip";
import { Detail } from "./screens/Detail";
import { Opportunities } from "./screens/Opportunities";
import { Overview } from "./screens/Overview";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // a 401 is not retried: the gate shows the login page instead (story #191)
        retry: (failures, error) => !isSignedOut(error) && failures < 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

function NotFound() {
  return <h1 className="font-heading text-2xl font-bold">Page not found</h1>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Overview />} />
      <Route path="/opportunities" element={<Opportunities />} />
      <Route path="/opportunities/:id" element={<Detail />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <TooltipProvider delayDuration={300}>
        <BrowserRouter>
          {/* nothing behind the gate is fetched before someone is signed in (story #191) */}
          <AuthGate>
            <DefinitionsProvider>
              <AppLayout>
                <AppRoutes />
              </AppLayout>
            </DefinitionsProvider>
          </AuthGate>
        </BrowserRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
