// The unit shown for money values (story #160): the currency code from display.currency (via
// /health), or the generic "net sales" when none is configured. Never hard-coded here.
import { useQuery } from "@tanstack/react-query";

import { api } from "./api/client";

export const NET_SALES = "net sales";

export function useMoneyUnit(): string {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  return health.data?.currency || NET_SALES;
}
