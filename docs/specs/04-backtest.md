# 04 Backtest (Epic E4, "Proof")

Status: DRAFT. FR-B1, FR-B2. A first-class deliverable.

## 1. Purpose and scope
| In | Out |
|---|---|
| Replay engines as of past dates using data up to then | Forecasting |
| Measure outcomes in following months | Measuring AI text quality |
| Hit rate and lift versus baseline | Causal claims |

## 2. Inputs and outputs
| Kind | Name |
|---|---|
| In | Engines parameterised by `as_of_date` (spec 03), `fact_sales` |
| Out | `bt_runs` (run id, as-of, config hash, algo_version) |
| Out | `bt_opportunities` (opportunities generated at as-of) |
| Out | `bt_outcomes` (per opportunity outcome) |
| Out | `bt_metrics` (per run, type, bucket) |
| CLI | `revint backtest run --as-of <date>`; `revint backtest report` |
| API | via spec 06 `/backtest/*` |

## 3. Replay rules
| ID | Rule |
|---|---|
| P1 | Engines see only rows with order date <= as-of (no leakage). Implemented by an as-of filter in the marts' inputs, not by trusting engine code |
| P2 | Default replay dates: as-of values spaced `backtest.step_months` apart such that a full `backtest.horizon_months` outcome window lies before 2020-02-29 |
| P3 | Same config, thresholds and algo_version as production; run records config hash |
| P4 | Dormancy and recovery use the same definitions as production; no tuning on outcome data |

## 4. Outcome definitions (per type)
Outcome window = `backtest.horizon_months` after as-of (default 3).

| Type | Hit if |
|---|---|
| Recovery | Net sales in the window >= `backtest.recovery_hit_pct` (default 50%) of the prior-period gap closed, i.e. window sales >= current-period sales + that share of the gap |
| Dormancy | Customer places >= 1 order in the window |
| Whitespace | Customer buys the category in the window |
| Cross-sell | Customer buys target category B in the window |

Outcome uses `v_net_sales` with the same config as the run.

## 5. Baseline
| Baseline | Definition |
|---|---|
| B-rand | Random sample of eligible customers, same count per type, fixed seed (`backtest.seed`) |
| B-size | Top-N customers by prior-period net sales (a naive "biggest accounts" rule) |
Primary baseline: B-size (harder, more honest); B-rand reported too.
Eligible population per type is stated explicitly (e.g. active in lookback).

## 6. Metrics
| Metric | Definition |
|---|---|
| Hit rate | hits / opportunities, by type and by priority bucket |
| Baseline hit rate | same on baseline picks of equal N |
| Lift | hit rate / baseline hit rate |
| Value captured (recovery) | Sum of recovered net sales in window; reported as an aggregate |
| Calibration | Hit rate by priority and confidence label (High should beat Low) |
| Coverage | opportunities / eligible customers |
Each metric carries N and a [x]% interval (Wilson for proportions). Small N is
labelled "low sample" (`backtest.min_n`, default 30).

## 7. Configurable parameters
| Key | Default |
|---|---|
| `backtest.horizon_months` | 3 |
| `backtest.step_months` | 3 |
| `backtest.n_replays` | [x] derived from date range |
| `backtest.recovery_hit_pct` | 50 |
| `backtest.seed` | 42 |
| `backtest.min_n` | 30 |
| `backtest.top_n` | same as engines |

## 8. Edge cases
- Window truncated by data end (2020-02-29): replay dropped, not shortened.
- Seasonality: first replays have less than 12 months history; engines
  needing a prior year are not run and are reported as skipped.
- Customer churn artefacts: no sales in window due to flagged data counted as miss; noted.
- Opportunity overlaps between replays reported but not de-duplicated.
- Honest-negative: if lift <= 1 for a type, it is reported as such.

## 9. Acceptance-level checks
- [ ] Leakage test: poison rows dated after as-of do not change output
- [ ] Hand-computed fixture: 10 customers, known hits, metrics match
- [ ] Deterministic with fixed seed
- [ ] Output lists N, hit rate, baseline, lift per type
- [ ] Run metadata (config hash, algo_version) stored
- [ ] Skipped replays are listed with reason
- [ ] Proof screen numbers equal `bt_metrics`

## 10. Dependencies
Spec 03 (as-of parameterised engines), spec 02. Feeds 06, 07.

## 11. OPEN QUESTIONS
- OPEN QUESTION: Horizon and number of replays. Default: 3-month
  horizon, 3-month step. Why: about 32 months of data limits the options.
- OPEN QUESTION: What counts as success for recovery? Default: 50% of
  gap closed. Why: no client definition.
- OPEN QUESTION: Do we backtest only dated engines, or also cross-sell
  (needs history to learn pairs)? Default: all four, pairs learned only
  from pre-as-of data. Why: strictest leakage rule.
- OPEN QUESTION: Is natural recovery (customers returning without action)
  acceptable as hit? Default: yes, the baseline absorbs it. Why: we
  cannot measure action effect without action history.
