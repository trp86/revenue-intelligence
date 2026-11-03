import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { DefinitionsProvider } from "./components/Definitions";

export function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });
}

function Placeholder({ title }: { title: string }) {
  return <h1 className="text-2xl font-semibold">{title}</h1>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Placeholder title="Overview" />} />
      <Route path="/opportunities" element={<Placeholder title="Opportunities" />} />
      <Route path="/opportunities/:id" element={<Placeholder title="Opportunity" />} />
      <Route path="*" element={<Placeholder title="Page not found" />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <DefinitionsProvider>
        <BrowserRouter>
          <AppShell>
            <AppRoutes />
          </AppShell>
        </BrowserRouter>
      </DefinitionsProvider>
    </QueryClientProvider>
  );
}
