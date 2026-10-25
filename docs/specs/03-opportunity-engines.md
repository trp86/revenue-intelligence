# 03 Opportunity engines (Epic E3)

Status: DRAFT. FR-O1 to FR-O6.

## 1. Purpose and scope
| In | Out |
|---|---|
| Recovery, dormancy, whitespace, cross-sell engines | Stretch: assortment expansion, price/discount (later) |
| Unified `opp_opportunities`, scoring, priority, confidence | Margin-based value |
| Value estimation, peer groups, config thresholds | AI text (spec 05) |

All engines are SQL in sql/30_opportunities/, run as-of a date
parameter (needed by the backtest, spec 04). Algorithms are
versioned: `algo_version` stored on every row.

## 2. Inputs and outputs
| Kind | Name |
|---|---|
| In | `mart_customer_month`, `mart_customer_category_month`, `mart_customer_profile`, `mart_peer_category_share`, `dim_*`, `config/settings.yaml` |
| Out | `opp_recovery`, `opp_dormancy`, `opp_whitespace`, `opp_crosssell` (per engine) |
| Out | `opp_opportunities` (unified, ranked) |
| Out | `opp_evidence` (long-form measured facts per opportunity, source for spec 05) |

Common columns in `opp_opportunities`: `opp_id` (deterministic hash
of type + customer + category + as_of), `type`, `customer_key`,
`category_key` (nullable), `as_of_date`, `algo_version`, `score`,
`priority` (High/Medium/Low), `confidence` (High/Medium/Low),
`value_low`, `value_high`, `value_level` (qualitative if no range),
`value_method`, `rank`, `reason_codes`.

## 3. Engines
### 3.1 Recovery (FR-O1)
- Compare the last `recovery.window_months` ending at as-of with the
  same months one year earlier (seasonality-aware).
- Opportunity if decline% >= `recovery.min_decline_pct` AND prior
  period net sales >= `recovery.min_prior_sales` AND customer had
  >= `recovery.min_prior_orders` orders in the prior window.
- Gap = prior - current (net sales). Uses `v_net_sales` marts only.
- Exclude customers meeting the dormancy rule (avoid double count;
  dormancy owns them). Test for this.

### 3.2 Dormancy (FR-O2)
- Customer's own interval = median days between order dates, with at
  least `dormancy.min_orders` orders.
- Dormant if days since last order > `dormancy.interval_multiple` x
  own interval AND > `dormancy.min_days` AND customer had sales in
  the `dormancy.lookback_months` before going quiet.
- Not a fixed day count. Customers below `min_orders` are not
  scored (reason code `insufficient_history`).

### 3.3 Whitespace (FR-O3)
- Peer group defined in config (default: same channel + same
  branch; fall back to channel only if group size <
  `whitespace.min_peer_size`).
- Category is whitespace if peer penetration >= `whitespace.min_peer_penetration`
  AND the customer bought none in the last `whitespace.lookback_months`.
- Gap = peer median category net sales per customer, over peers who
  buy it, scaled by nothing else (no invented uplift).

### 3.4 Cross-sell (FR-O4)
- Category (or product) pairs A -> B at the customer level with
  support >= `crosssell.min_support` (customers), confidence >=
  `crosssell.min_confidence`, lift >= `crosssell.min_lift`.
- Candidate: customer bought A in lookback, never bought B.
- Pairs below thresholds suppressed and counted in a run summary.

## 4. Scoring (FR-O5)
`score` (0-100) = weighted sum of normalised components. Weights in
config; defaults:

| Component | Default weight |
|---|---|
| Value (percentile rank of gap within type) | 0.40 |
| Evidence strength (engine-specific, 0..1) | 0.30 |
| Recency / urgency | 0.20 |
| Data quality (share of the customer's lines unflagged) | 0.10 |

Priority from score cut-offs `scoring.priority_high` (default 70) and
`scoring.priority_medium` (default 40). Confidence from evidence
strength and data-quality share, cut-offs in config.
Ties broken by `value_high`, then `customer_key` (deterministic).

## 5. Value estimation
| Rule | |
|---|---|
| Value is a documented range from measured gaps: low = `value.low_factor` x gap, high = `value.high_factor` x gap. Defaults 0.25 and 0.75 [x] | |
| Each row states `value_method` text | |
| If gap cannot be defended (e.g. missing prior period) set `value_level` (High/Medium/Low) and leave range NULL | |
| Value is labelled "Estimate" in the UI, never "Measured" | |

## 6. Configurable parameters (proposed defaults)
| Key | Default |
|---|---|
| `recovery.window_months` | 3 |
| `recovery.min_decline_pct` | 20 |
| `recovery.min_prior_sales` | [x] |
| `recovery.min_prior_orders` | 3 |
| `dormancy.min_orders` | 4 |
| `dormancy.interval_multiple` | 2.0 |
| `dormancy.min_days` | 45 |
| `dormancy.lookback_months` | 12 |
| `whitespace.min_peer_size` | 10 |
| `whitespace.min_peer_penetration` | 0.5 |
| `whitespace.lookback_months` | 12 |
| `crosssell.min_support` | 30 |
| `crosssell.min_confidence` | 0.3 |
| `crosssell.min_lift` | 1.2 |
| `top_n_per_type` | [x] |

All numeric defaults are proposals for review, not facts about the data.

## 7. Edge cases
- New customers (< min history): no opportunity; counted in summary.
- Negative net sales periods: gap computed on net; flagged in reason codes.
- Customer with several branches: opportunity at customer level;
  branch shown as latest.
- Customers with `f_multi_identity`: opportunity allowed, confidence
  capped at Medium.
- Flagged lines (duplicates, blank Void): included per spec 02 config;
  data-quality component reduces score.
- Re-run with same as-of and config gives identical `opp_id`s and ranks.

## 8. Acceptance-level checks
- [ ] Synthetic fixtures: one customer per engine triggers exactly
      once; a near-threshold customer does not
- [ ] Dormancy uses own interval: two customers with equal days since
      last order but different intervals get different outcomes
- [ ] No customer appears in both recovery and dormancy for the same as-of
- [ ] Changing a threshold in config changes results with no code edit
- [ ] Every row has non-null `score`, `priority`, `confidence`, evidence rows and value or `value_level`
- [ ] Deterministic ordering (run twice, identical)
- [ ] No opportunity uses data after `as_of_date` (leakage test, shared with spec 04)

## 9. Dependencies
Spec 02 (marts), spec 10 (config). Feeds 04, 05, 06.

## 10. OPEN QUESTIONS
- OPEN QUESTION: Peer group definition. Default: channel + branch with
  channel fallback. Why: docs say "defined in config" only.
- OPEN QUESTION: Value estimation method. Default: factor range of
  measured gap (above). Why: no cost or conversion data to justify more.
- OPEN QUESTION: Which engine is the "one more" besides recovery and
  whitespace? Default: dormancy. Why: simplest to defend and test.
- OPEN QUESTION: Is the engine unit customer or customer x branch?
  Default: customer. Why: identity decision.
- OPEN QUESTION: Category or product level for cross-sell? Default:
  category. Why: 181 products is sparse per customer.
