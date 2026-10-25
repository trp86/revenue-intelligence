# 09 Action tracking (Epic E9)

Status: DRAFT. FR-T1 to FR-T3. Also covers demo hardening scope.

## 1. Purpose and scope
| In | Out |
|---|---|
| Approve, assign, defer (with reason), set status | Autonomous execution, notifications/email |
| Audit trail in app.duckdb | Multi-user permissions, SSO |
| Demo hardening checklist | New features |

## 2. Inputs and outputs
| Kind | Name |
|---|---|
| Store | data/app.duckdb (git-ignored; never inside the warehouse file) |
| Tables | `app_actions` (current state), `app_action_events` (append-only history) |
| API | POST/PATCH/GET /actions (spec 06) |
| UI | Approve / Assign / Defer controls on Opportunity Detail; optional tracker screen |
| CLI | `revint app init`, `revint app export-actions` (CSV, counts-safe) |

## 3. Model
`app_actions`: `action_id`, `opp_id`, `status`, `owner`, `defer_reason`,
`defer_until` (nullable), `note`, `created_by`, `created_at`,
`updated_at`, `opp_snapshot_json` (score, type, value range at decision time).

`app_action_events`: `event_id`, `action_id`, `from_status`, `to_status`,
`actor`, `at`, `payload_json`.

## 4. Statuses and transitions (FR-T2)
Statuses: New, Approved, Assigned, Done, Deferred.

| From | To | Condition |
|---|---|---|
| New | Approved | none |
| New | Deferred | reason required |
| Approved | Assigned | owner required |
| Assigned | Done | none; optional note |
| Approved / Assigned | Deferred | reason required |
| Deferred | New | re-open; reason kept in events |
| Done | (none) | terminal in POC |

Any other transition returns 409. An opportunity with no action row is
shown as `New`. Approving an opportunity does not require an AI brief.

## 5. Rules
| ID | Rule |
|---|---|
| T1 | One current action per `opp_id` per as-of; history in events |
| T2 | Every change appends an event; events are never edited |
| T3 | Opportunities regenerate with the same `opp_id` for the same inputs so actions stay attached (spec 03 determinism). If an `opp_id` disappears after a rebuild, the action is shown as "no longer detected", not deleted |
| T4 | Owner is a free-text name in POC (no user directory) |
| T5 | `defer_until` optional; when passed the item returns to New with a visible "defer expired" marker (computed at read time) |
| T6 | Rebuilding the warehouse never touches app.duckdb |
| T7 | Single writer: only the API process writes app.duckdb; CLI uses the API or runs when API is stopped |

## 6. Demo hardening (end of E9)
- [ ] Seed script for demo state (aggregate-level, no customer data in repo)
- [ ] Clean-clone run: `uv sync`, `uv run revint build all`, start API and UI works from README
- [ ] Offline demo mode with the fake AI client and pre-generated briefs
- [ ] Error-free console on each screen
- [ ] Known limitations list on the Definitions screen

## 7. Configurable parameters
| Key | Default |
|---|---|
| `app.db_path` | `data/app.duckdb` |
| `actions.defer_reasons` | list: Customer inactive, Out of scope, Low value, Needs data check, Other [x] |
| `actions.require_owner_on_assign` | true |

## 8. Edge cases
- Two users act at once: second gets 409 with the current state (compare `updated_at`).
- Reason text length cap [x] 500 chars; no customer-level data required.
- app.duckdb locked/corrupt: API returns 503 for action endpoints only.
- Schema changes: versioned migrations `app_schema_version`.

## 9. Acceptance-level checks
- [ ] Allowed transitions succeed; each disallowed pair returns 409 (parametrised test)
- [ ] Defer without reason and assign without owner are rejected
- [ ] Event appended per change; history reconstructs current state
- [ ] Warehouse rebuild leaves actions intact (test)
- [ ] Action survives with the same `opp_id` after identical rebuild
- [ ] Missing opp after rebuild shows "no longer detected"
- [ ] app.duckdb path is git-ignored; no warehouse table lives in it

## 10. Dependencies
Specs 06 (endpoints), 07 (controls), 05 (shared app.duckdb conventions),
03 (stable `opp_id`), 10 (CLI, config).

## 11. OPEN QUESTIONS
- OPEN QUESTION: Defer reasons list. Default: above. Why: none given.
- OPEN QUESTION: Do owners come from a list? Default: free text. Why: no user directory.
- OPEN QUESTION: Can a Done action be reopened? Default: no. Why: keep audit simple for POC.
- OPEN QUESTION: Should Done trigger an outcome check against later data? Default: out of scope. Why: forecasting/attribution not in scope.
