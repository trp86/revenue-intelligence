# 00 Overview

Status: DRAFT. Sources: docs/decisions.md, docs/requirements.md.

## 1. Purpose and scope
Help SALES MANAGERS decide where to focus to grow revenue. Answers:
where is the extra revenue, why does the opportunity exist, what
should the team do next. Not a reporting dashboard.

| In scope (Phase 1 POC) | Out of scope |
|---|---|
| RAW SCJ SALES order lines (core) | Oct 2019 DC (batteries), BBL, Beverage, YLT target |
| July 2019 closing report (reference: targets, reconciliation) | Oct SCJ sheet (duplicates master), lookups, old extracts |
| Recovery, dormancy, whitespace, cross-sell | Margin, inventory, promotion, forecasting |
| Backtest (first-class deliverable) | Competitor / macro data, vector DB / RAG |
| Gemini explanations over supplied evidence | Autonomous execution of actions |
| Approve / assign / defer | Multi-tenant admin, SSO |
| Stretch only: assortment expansion, price/discount | |

## 2. Users
| User | Need |
|---|---|
| Sales manager (primary) | Decide focus, owner, approve or defer |
| Executive (secondary) | Overview of where to focus |
| Account owner (secondary) | Brief for an assigned opportunity |

## 3. Data scope (from docs)
- Core: about 662k order lines, about 12k customers, 181 products,
  2017-07-02 to 2020-02-29. As-of date 2020-02-29 (config).
- Pivots are validation fixtures, never data.
- Raw data is confidential: never committed, never sent unmasked
  to external services.

## 4. Success criteria (from requirements section 8)
- [ ] One command builds bronze, silver, gold; reconciliation passes
- [ ] Recovery, whitespace and one more engine rank opportunities
      with evidence
- [ ] Backtest result available and explainable
- [ ] Gemini output schema-valid, uses only supplied evidence
- [ ] Manager goes Overview -> opportunity -> evidence + AI -> approve
      or assign
- [ ] Assistant answers the suggested questions correctly, with
      evidence

## 5. Principles (binding on all specs)
1. Python/SQL calculates; Gemini communicates.
2. Flag, never delete (sole exception: the documented stray row,
   spec 01 decision D1).
3. Net sales is provisional and defined once, from config.
4. Every number shows its definition; every recommendation links to
   evidence.
5. Colour is never the only signal.
6. Separate Measured fact / Estimate / AI suggestion everywhere.

## 6. Glossary
| Term | Definition |
|---|---|
| Order line | One row of RAW SCJ SALES |
| Net sales | Provisional measure chosen in config (default Net AMOUNT) |
| As-of date | Date up to which data is used to build opportunities; default 2020-02-29 |
| Opportunity | A ranked, evidence-backed candidate action for a customer (or customer x category) |
| Engine | Rule/SQL module producing one opportunity type |
| Peer group | Set of comparable customers defined in config |
| Whitespace | Category bought by peers but not by the customer |
| Dormant | Inactive beyond the customer's own buying interval |
| Evidence package | Small JSON of measured facts sent to Gemini |
| Bronze / Silver / Gold | Raw-as-text / typed+flagged / star schema + marts |
| Flag | Boolean/enum column marking a data-quality issue; row is kept |
| Backtest | Replay as of a past date; compare predictions with later outcomes |
| Hit rate / lift | Share of opportunities with positive outcome / ratio versus baseline |

## 7. Dependencies
Depends on: none. All other specs depend on this for vocabulary.

## 8. Acceptance-level checks
- [ ] Every other spec uses the terms above consistently.
- [ ] No spec contradicts docs/decisions.md.

## 9. OPEN QUESTIONS
- OPEN QUESTION: Who is the named business owner who answers the
  open business questions in decisions.md section 3? Proposed
  default: the POC sponsor; record answers via PR to decisions.md.
  Why: stories cannot be Ready with undefined owners of answers.
- OPEN QUESTION: Is "region" a real attribute in the source, or
  derived from branch? Proposed default: derive from branch via a
  config mapping. Why: FR-U2 filters on region; source unknown.
