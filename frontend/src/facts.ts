// Plain-language labels of the measured facts (opp_evidence), shared by the Detail page and the
// preview. The definitions themselves come from /definitions (config/definitions.yaml).
export const FACT_LABELS: Record<string, string> = {
  days_since_last_order: "Days since the last order",
  median_interval_days: "Usual days between orders",
  n_orders: "Orders up to the as-of date",
  last_order_date: "Last order date",
  lookback_net_sales: "Net sales before going quiet",
  prior_net_sales: "Net sales, same months last year",
  current_net_sales: "Net sales, latest months",
  prior_orders: "Orders, same months last year",
  decline_pct: "Decline on last year",
  n_peers: "Peers in the group",
  n_buying_peers: "Peers buying the category",
  peer_penetration: "Share of peers buying it",
  peer_median_net_sales: "Median net sales of buying peers",
  support: "Customers who bought both",
  confidence: "Buyers of A who also bought B",
  lift: "Lift",
  median_b_net_sales: "Median net sales in B",
};

export const factLabel = (fact: string): string => FACT_LABELS[fact] ?? fact.replaceAll("_", " ");
