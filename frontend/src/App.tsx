import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { DefinitionsProvider } from "./components/Definitions";
import { AppLayout } from "./components/layout/AppLayout";
import { Toaster } from "./components/ui/toaster";
import { TooltipProvider } from "./components/ui/tooltip";
import { Detail } from "./screens/Detail";
import { Opportunities } from "./screens/Opportunities";
import { Overview } from "./screens/Overview";

export function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });
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
        <DefinitionsProvider>
          <BrowserRouter>
            <AppLayout>
              <AppRoutes />
            </AppLayout>
          </BrowserRouter>
        </DefinitionsProvider>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
