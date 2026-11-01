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
`category` (text, nullable; there is no category key in gold), `as_of_date`, `algo_version`, `score`,
`priority` (High/Medium/Low), `confidence` (High/Medium/Low),
`value_low`, `value_high`, `value_level` (qualitative if no range),
`value_method`, `rank`, `reason_codes`.

### Opportunity schema and run summary (story #107)
The opportunity stage is `sql/30_opportunities`, run in filename order in one transaction by `revint.opportunities.run_opportunities`; every run rebuilds every table in full, and a failed run leaves the previous tables in place.
- `02_schema.sql` creates the empty tables and the macro `opp_id(type, customer_key, category, as_of_date)`: the md5 of a JSON list of the four values, so the id is the same on every run, a NULL category differs from an empty one, and a separator inside a value cannot make two ids collide. `revint.opportunities.opp_id` gives the same id in Python.
- `opp_engines`: the four engines (`dormancy`, `recovery`, `whitespace`, `crosssell`) and the `algo_version` each stores on every row (`<engine>-1`). A change to an engine's rule raises its version.
- `opp_<engine>`: the opportunities one engine found. Identity columns as above (`opp_id` is the primary key), then `gap` and `reason_codes`; an engine adds its own columns.
- `opp_evaluations`: one row per customer (and category) an engine looked at, with its outcome: `triggered` or the reason code it was suppressed (for example `insufficient_history`).
- `90_run_summary.sql` runs after the engines and builds `opp_run_summary`: per engine `as_of_date`, `algo_version`, `n_evaluated`, `n_triggered`, `n_suppressed` and `suppressed_by_reason` (map of reason code to count). Counts only. It fails the stage when an evaluation names an unknown engine, a customer is evaluated twice, a trigger has no opportunity row (or the reverse), or a row carries another version.

### As-of inputs (story #106)
The engines read only the as-of inputs, built by `revint.opportunities.build_asof_inputs` from `sql/30_opportunities/01_asof_inputs.sql`, never the all-data marts: `mart_customer_profile` and `mart_peer_category_share` are computed over every sale, so a run for an earlier as-of date would see the future through them (spec 04 P1). Each input repeats the logic of a mart, with one difference: only included sales lines dated on or before the as-of date count. A line with no date cannot be placed before the as-of date and is left out (the marts keep it with a NULL month).
- `asof_orders`: one row per customer and order date (an order is a distinct customer and date), with its net sales and lines.
- `asof_customer_month`, `asof_customer_category_month`: as `mart_customer_month` and `mart_customer_category_month`, zero filled (`marts.zero_fill`) only up to the month of the as-of date.
- `asof_customer_profile`: as `mart_customer_profile` (last order, number of orders, median and mean interval, peer keys from `peer_groups.columns`).
- `asof_peer_category_share`: as `mart_peer_category_share`, with the same `peer_groups` fallback.
Every input carries `as_of_date`. The date is `asof.date`; `with_asof(settings, date)` gives a copy of the settings for one run, so the config file is never edited. At the last day of the data the inputs equal the four marts, on the real file with 0 differing rows; at 2019-06-30 they hold 11,044 customers and no order after 28 June 2019.

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
  `peer_groups.min_size`). The group and its minimum size are the
  `peer_groups` settings from spec 02 (story #72); there is no separate
  whitespace minimum (story #104).
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
| `recovery.min_prior_sales` | 0 (no minimum); provisional until story E3-2 profiles it |
| `recovery.min_prior_orders` | 3 |
| `dormancy.min_orders` | 4 |
| `dormancy.interval_multiple` | 2.0 |
| `dormancy.min_days` | 45 |
| `dormancy.lookback_months` | 12 |
| `whitespace.min_peer_penetration` | 0.5 |
| `whitespace.lookback_months` | 12 |
| `crosssell.min_support` | 30 |
| `crosssell.min_confidence` | 0.3 |
| `crosssell.min_lift` | 1.2 |
| `crosssell.lookback_months` | 12 (story #104: the months in which a candidate bought A) |
| `opportunities.top_n_per_type` | unset (keep all); provisional until story E3-2 profiles it |
| `scoring.weight_value` / `weight_evidence` / `weight_urgency` / `weight_data_quality` | 0.40 / 0.30 / 0.20 / 0.10 (they must sum to 1) |
| `scoring.priority_high` / `priority_medium` | 70 / 40 (high above medium) |
| `scoring.confidence_high` / `confidence_medium` | 0.7 / 0.4 (high above medium) |
| `value.low_factor` / `high_factor` | 0.25 / 0.75 (low below high) |

All numeric defaults are proposals for review, not facts about the data. They are validated and loaded by the `Settings` model (story #104): an unknown key or an out-of-range value fails naming the key, and every key is a SQL parameter (`$recovery_window_months` and so on).

## 7. Edge cases
- New customers (< min history): no opportunity; counted in summary.
- Negative net sales periods: gap computed on net; flagged in reason codes.
- Customer with several branches: opportunity at customer level;
  branch shown as latest.
- Customers with `f_multi_identity`: opportunity allowed, confidence
  capped at Medium.
- Exact-duplicate copies and the stray row are already absent from the
  fact (spec 01 D4). Other flagged lines (blank Void with
  `void_flag = 0`, free goods) are included; the data-quality
  component reduces score.
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
