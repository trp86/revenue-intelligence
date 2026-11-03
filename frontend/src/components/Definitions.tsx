// The definitions of every number, loaded once from /definitions (spec 07 section 6).
import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";

import { api } from "../api/client";
import type { Definition } from "../api/types";

const DefinitionsContext = createContext<Map<string, Definition>>(new Map());

export function DefinitionsProvider({ children }: { children: ReactNode }) {
  const query = useQuery({ queryKey: ["definitions"], queryFn: api.definitions,
    staleTime: Infinity });
  const map = new Map((query.data?.definitions ?? []).map((d) => [d.id, d]));
  return <DefinitionsContext.Provider value={map}>{children}</DefinitionsContext.Provider>;
}

export function useDefinition(id: string): Definition | undefined {
  return useContext(DefinitionsContext).get(id);
}
