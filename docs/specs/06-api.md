# 06 API (Epic E6)

Status: DRAFT. FastAPI; React calls this only.

## 1. Purpose and scope
| In | Out |
|---|---|
| REST endpoints, pydantic contracts, allow-listed query layer | Business logic in routers |
| Error model, pagination, CORS, auth stance | SSO, multi-tenant |
| Serving AI briefs and actions | Direct DuckDB/Gemini access from React |

Layers: router (thin) -> service -> query layer (`src/revint/query/`)
-> DuckDB read-only connection on the warehouse; writes only to
app.duckdb via spec 09/05 services.

## 2. Endpoints
All under `/api/v1`. JSON. Response models are pydantic.

**POC scope (2026-11-02, docs/decisions.md section 11):** only `/health`, `/definitions`,
`/overview`, `/opportunities`, `/opportunities/{opp_id}` and the two `/brief` endpoints are
built. `/customers`, `/explore/*`, `/assistant/chat`, `/backtest/*`, `/actions` and
`/data-quality` are out of scope for the POC (E4, E8 and E9 were dropped).

| Method | Path | Purpose |
|---|---|---|
| GET | /health | Liveness + data build info (as-of, net sales field, build time) |
| GET | /definitions | Metric and dimension definitions (from config/definitions.yaml) |
| GET | /overview | KPIs, opportunities by type, top N |
| GET | /opportunities | Ranked list; filters: region, channel, branch, type, status, priority; `page`, `page_size`, `sort` |
| GET | /opportunities/{opp_id} | Detail: measured facts, estimate, quality notes |
| GET | /opportunities/{opp_id}/brief | Latest AI brief + provenance (404 if none) |
| POST | /opportunities/{opp_id}/brief | Generate (or return cached) brief |
| GET | /customers/{customer_key} | Customer 360 data |
| GET | /explore/catalog | Allowed measures, dimensions, filters |
| POST | /explore/query | Run an allow-listed query (section 4) |
| POST | /explore/export | CSV of the same query |
| POST | /assistant/chat | Tool-based chat turn (spec 08) |
| GET | /backtest/summary, /backtest/runs/{id} | Proof data |
| POST | /actions | Create action decision (spec 09) |
| PATCH | /actions/{action_id} | Change status/owner/reason |
| GET | /actions | List by status/owner |
| GET | /data-quality | Rule results and reconciliation (counts only) |

### Built in story #134
`uv run revint serve` starts the API (FastAPI and uvicorn) on `api.host`:`api.port`, 127.0.0.1:8000 by
default. `revint.api.app` holds the thin routers; `revint.api.service` is the only module that opens
DuckDB, and it opens the warehouse read-only for each request. The response models are in
`revint.api.models`, and the committed schema is `docs/openapi.json`
(`uv run python -m revint.api.openapi`; a test fails on drift). Settings: `api.page_size_default` 25,
`api.page_size_max` 200, `api.top_n_overview` 10, `api.cors_origins` (the Vite dev origin). Filters on
`/opportunities`: `type`, `priority`, `confidence` (allow-listed), `branch` and `channel` (the
normalised labels of `dim_customer`, bound as parameters); `sort` is `rank`, `score` or `value_high`.
A bad parameter is 400, an unknown id 404, and a warehouse or opportunity tables that are not built
503, all with `{error: {code, message}}`. The customer code and name are returned to the app user
(provisional); masking applies only to Gemini.

### Brief endpoints (story #138)
`GET /opportunities/{opp_id}/brief` returns the latest valid brief with its provenance (model,
prompt version, time, validation and review status), 404 `no_brief` when there is none and 404
`not_found` for an unknown opportunity. `POST` generates it, or returns the cached one
(`provenance.cached`). AI turned off gives 503 `ai_disabled`; Gemini unreachable, the daily limit,
or an answer that fails the guardrails gives 503 `ai_unavailable`. A failed answer is never served.
`revint.api.briefs` is the service; the router never calls Gemini.

## 3. Contracts and conventions
- Every numeric metric in a response is an object
  `{value, unit, definition_id}` so the UI can show its definition.
- `kind` field on content blocks: `measured` / `estimate` / `ai`.
- Error body: `{error: {code, message, detail?}}`; HTTP 400 validation, 404, 409 conflict, 422 pydantic, 503 AI unavailable (never fails the page).
- Pagination: `page`, `page_size` (default 25, max 200); response has `total`.
- Customer identifiers: API returns the real customer label to the app user; masking applies only to Gemini (spec 05). [x] confirm.
- OpenAPI schema committed at docs/openapi.json and checked in CI for drift.

## 4. Allow-listed query layer (shared by Explore and assistant)
One module, one definition. Request:

```
{ measure: <id>, dimensions: [<id>...], filters: [{dim, op, values}],
  period: {from, to}, compare_to: "prior_period"|"prior_year"|null,
  sort, limit }
```

| Rule | |
|---|---|
| Measures, dimensions, ops come from an allow-list in config/explore.yaml | |
| SQL built from templates over marts/`v_net_sales` with bound parameters; no string interpolation of user input, no free-form SQL | |
| Max `explore.max_rows` (default 5000), max dimensions `explore.max_dims` (default 3), query timeout `explore.timeout_s` (default 10) | |
| Reads only marts and fact via the read-only connection | |
| Response includes `definition`, `sql_template_id`, row count, `as_of` | |
| Small-cell safety: not required (internal tool); revisit if client shares externally | |

## 5. Security and config
- Gemini key server-side; never in responses.
- CORS: only the Vite dev origin / configured origin.
- No auth in POC; `X-User` header (name) stored on actions [x] confirm. Bind to localhost by default.
- Warehouse opened read-only; app.duckdb opened by one writer process.

## 6. Configurable parameters
| Key | Default |
|---|---|
| `api.page_size_default` / `max` | 25 / 200 |
| `explore.max_rows`, `max_dims`, `timeout_s` | 5000, 3, 10 |
| `api.cors_origins` | `http://localhost:5173` |

## 7. Edge cases
- Warehouse missing/not built: /health returns `not_ready`, other endpoints 503 with a helpful message.
- Empty result: 200 with `rows: []` and a reason, never an error.
- AI disabled: brief endpoints return 503 `ai_disabled` and the UI shows evidence only.
- Concurrent writes to app.duckdb serialised by a single service.

## 8. Acceptance-level checks
- [ ] Each endpoint has a contract test (status, schema)
- [ ] Injection attempts in filters/sort are rejected or bound (test)
- [ ] Unknown measure/dimension returns 422
- [ ] Query layer identical for Explore and assistant (same function called)
- [ ] Row cap and timeout enforced
- [ ] OpenAPI drift check passes
- [ ] No router imports duckdb directly (import test)
- [ ] Metrics carry `definition_id` that exists in /definitions

## 9. Dependencies
Specs 02, 03, 04, 05, 09, 10. Feeds 07, 08.

## 10. OPEN QUESTIONS
- OPEN QUESTION: Authentication/user identity for "assign" and audit.
  Default: no auth, free-text user name header. Why: SSO out of scope.
- OPEN QUESTION: Should the real customer name appear in the UI?
  Default: yes (internal manager tool), masked only for Gemini. Why:
  decisions.md restricts external services only.
- OPEN QUESTION: Is "region" filter backed by data? See spec 00.
  Default: from branch mapping.
