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
- Built in `sql/30_opportunities/04_recovery.sql` (story #109), after dormancy. The current window runs from the first day of the month `window_months - 1` months before the as-of month to the as-of date; the prior window is the same dates one year earlier. Decline % = (prior - current) / prior x 100. All three limits are "at least". A customer with no positive prior net sales is not an opportunity (`no_prior_sales`). Suppression reasons, first that applies: `dormant`, `no_prior_sales`, `below_min_prior_orders`, `below_min_prior_sales`, `below_min_decline`. A triggered row has `reason_codes` [`decline_at_least_min`, `prior_sales_at_least_min`, `prior_orders_at_least_min`], plus `negative_current_period` when current net sales are below zero, and adds `current_sales`, `prior_sales`, `prior_orders` and `decline_pct`. Real file, as of 2020-02-29: 12,239 evaluated, 359 triggered (equal to the #105 profile's "not dormant"), 0 in both recovery and dormancy; suppressed 2,425 `dormant`, 6,263 `no_prior_sales`, 2,743 `below_min_prior_orders`, 4 `below_min_prior_sales`, 445 `below_min_decline`.

### 3.2 Dormancy (FR-O2)
- Customer's own interval = median days between order dates, with at
  least `dormancy.min_orders` orders.
- Dormant if days since last order > `dormancy.interval_multiple` x
  own interval AND > `dormancy.min_days` AND customer had sales in
  the `dormancy.lookback_months` before going quiet.
- Not a fixed day count. Customers below `min_orders` are not
  scored (reason code `insufficient_history`).
- Built in `sql/30_opportunities/03_dormancy.sql` (story #108). Every limit is strict, so a customer exactly at a limit does not trigger; `min_orders` is a floor. "Sales before going quiet" is positive net sales in the `lookback_months` months ending with the month of the last order, and the gap is those net sales (approved). The unknown customer (-1) is not evaluated. A customer that does not trigger is suppressed with the first test it fails: `insufficient_history`, `within_own_interval`, `within_min_days`, `no_sales_in_lookback`. A dormant row has `reason_codes` [`beyond_own_interval`, `beyond_min_days`, `sales_in_lookback`] and adds `last_order_date`, `days_since_last_order`, `median_interval_days` and `n_orders`. Real file, as of 2020-02-29: 12,239 evaluated, 2,425 dormant (equal to the #105 profile), suppressed 4,855 `insufficient_history`, 4,920 `within_own_interval` and 39 `within_min_days`.

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
- Built in `sql/30_opportunities/05_whitespace.sql` (story #110). The peer group is `asof_peer_assigned` in the as-of inputs (the same fallback as `asof_peer_category_share`, now written once). Penetration and the gap are judged for each customer without the customer itself; a peer buys a category when its net sales in it up to the as-of date are above zero. "Bought none in the lookback" means no sales line in the category in the `lookback_months` months ending with the as-of month. Evaluated: each known customer and each category (not 'Unknown') bought in its peer group. Suppression reasons, first that applies: `no_peers`, `below_min_penetration`, `bought_in_lookback`. A triggered row has `reason_codes` [`peer_penetration_at_least_min`, `not_bought_in_lookback`], plus `peer_fallback` and `peer_group_below_min_size` when they apply, and adds `peer_penetration`, `n_peers`, `n_buying_peers`, `f_fallback` and `f_below_min_size`. Real file, as of 2020-02-29: 356,997 customer-category pairs evaluated, 15,293 triggered across 7,837 customers (206 in a fallback group, 114 still below the minimum size); suppressed 328,215 `below_min_penetration`, 13,471 `bought_in_lookback`, 18 `no_peers`. The #105 profile counted 15,724 pairs because it did not leave the customer out of its own peers.

### 3.4 Cross-sell (FR-O4)
- Category (or product) pairs A -> B at the customer level with
  support >= `crosssell.min_support` (customers), confidence >=
  `crosssell.min_confidence`, lift >= `crosssell.min_lift`.
- Candidate: customer bought A in lookback, never bought B.
- Pairs below thresholds suppressed and counted in a run summary.
- Built in `sql/30_opportunities/06_crosssell.sql` (story #111), at category level. Pair measures use every known customer's purchases up to the as-of date (a buy is net sales above zero): support = customers who bought both, confidence = support / buyers of A, lift = confidence / (buyers of B / customers who bought any category). All three limits are "at least". Every ordered pair with support above zero is kept in `opp_crosssell_pairs` with its outcome (`passed` or the first failing threshold: `below_min_support`, `below_min_confidence`, `below_min_lift`). A candidate bought A in the `crosssell.lookback_months` months ending with the as-of month and has no line in B up to the as-of date. One evaluation and at most one opportunity per customer and category B: triggered when any of its pairs passes, else suppressed with the threshold its furthest pair failed. A triggered row keeps the strongest passing pair (highest lift, then confidence, support, name of A) in `category_a`, `support`, `confidence` and `lift`. Gap = median net sales in B among customers who bought both (approved). 'Unknown' is neither A nor B. Real file, as of 2020-02-29: 1,200 pairs (383 passed, 374 below support, 406 below confidence, 37 below lift); 262,159 customer-category evaluations, 46,466 triggered across 7,392 customers. The #105 profile counted 86,912 candidates per customer and pair, with pair measures over the lookback only.

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

Built in `sql/30_opportunities/08_scoring.sql` (story #113), which fills `opp_opportunities` from the four engine tables and `opp_value`. Components, each 0 to 1 (approved on #113):
- value: `percent_rank` of the gap within its engine (0 for an undefended gap);
- evidence, capped at 1: dormancy days quiet / own median interval; recovery `decline_pct` / 100; whitespace the peer penetration; cross-sell the confidence;
- urgency: dormancy 1 - min(1, days quiet / `scoring.urgency_horizon_days`, default 365); recovery 1 (the decline is in the current window); whitespace and cross-sell `scoring.urgency_neutral` (default 0.5, no change event). Both keys are provisional;
- data quality: the share of the customer's sales lines up to the as-of date with none of `f_zero_value_with_qty`, `f_negative_qty`, `f_negative_value` or an `f_bad_` flag.

`score` = 100 x the weighted sum, rounded to 2 decimals. Confidence uses the lower of evidence and data quality. It is capped at Medium (reason code `confidence_capped`) for a customer with `f_multi_identity` or a whitespace row whose peer group is still below the minimum size. `rank` 1 is best: by score, then `value_high`, then `customer_key`, then `opp_id`, so every rank is unique. Real file, as of 2020-02-29: 64,543 opportunities, score 21.95 to 96.45 (median 52.29); priority 10,871 High, 40,270 Medium, 13,402 Low; confidence 7,450 High, 40,171 Medium, 16,922 Low; 3,628 capped.

## 5. Value estimation
| Rule | |
|---|---|
| Value is a documented range from measured gaps: low = `value.low_factor` x gap, high = `value.high_factor` x gap. Defaults 0.25 and 0.75 [x] | |
| Each row states `value_method` text | |
| If gap cannot be defended (e.g. missing prior period) set `value_level` (High/Medium/Low) and leave range NULL | |
| Value is labelled "Estimate" in the UI, never "Measured" | |

Built in `sql/30_opportunities/07_value.sql` (story #112), after the engines, into `opp_value` (one row per opportunity of every engine: `opp_id`, `type`, `gap`, `f_defensible_gap`, `value_low`, `value_high`, `value_level`, `value_method`); E3-10 copies the value columns into `opp_opportunities`. A gap is defensible when it is not NULL and above zero. `value_level` is set on every row from the gap's `percent_rank` within its engine: at least 2/3 High, at least 1/3 Medium, else Low; an undefended gap is Low with a NULL range. `value_method` names the factors and what the gap measures. Real file, as of 2020-02-29: every one of the 64,543 gaps is defensible, so every row has a range; the levels split into thirds within each engine.

## 6. Configurable parameters (proposed defaults)
| Key | Default |
|---|---|
| `recovery.window_months` | 3 |
| `recovery.min_decline_pct` | 20 |
| `recovery.min_prior_sales` | 25000; provisional (story #105, near p25 of prior-window net sales), the maintainer confirms |
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
| `opportunities.top_n_per_type` | 250; provisional (story #105), the maintainer confirms |
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

### Threshold profile findings (story #105; provisional, the maintainer confirms)
Run with `uv run python -m revint.threshold_profile` (counts and percentiles only; it builds the as-of inputs on a temporary copy of the warehouse). Real file, as of 2020-02-29, at the defaults of section 6 with `min_prior_sales` 0:
- Recovery: 4,912 customers ordered in the prior window. Prior-window net sales per customer: p10 15,600, p25 28,800, p50 57,800, p75 144,600, p90 405,157. Pass on their own: `min_decline_pct` 3,051, `min_prior_orders` 1,073. Flagged by all three: 622 (362 not dormant). Flagged with `min_prior_sales` at p10/p25/p50/p75/p90: 615 / 609 / 565 / 360 / 170. No natural break (`min_prior_orders` already removes most small customers), so the minimum is a judgement: 25000, near p25, chosen.
- Dormancy: 12,239 customers; 4,855 `insufficient_history`; flagged 2,425.
- Whitespace: 12,211 evaluated (28 in a peer group below `peer_groups.min_size`); 15,724 customer-category pairs flagged across 8,159 customers.
- Cross-sell: 8,557 customers and 36 categories in the lookback; 322 of 1,260 ordered pairs pass all three thresholds; 86,912 candidates across 7,187 customers.
- Whitespace and cross-sell produce far more than a person can review, so `opportunities.top_n_per_type` is 250 per engine.

The profile's reading of each rule, for the engine stories (E3-5 to E3-8) to confirm: recovery compares the last `window_months` months up to the as-of date with the same dates a year earlier and evaluates customers with an order in the prior window; dormancy's "sales before going quiet" is positive net sales in the `lookback_months` months up to the last order; whitespace evaluates a customer only when its peer group after fallback has at least `peer_groups.min_size` customers; a cross-sell candidate bought A in the lookback and never bought B up to the as-of date. The unknown customer and the 'Unknown' category are left out.
