# 05 AI layer (Epic E5)

Status: DRAFT. FR-A1 to FR-A5. Python/SQL calculates; Gemini communicates.

## 1. Purpose and scope
| In | Out |
|---|---|
| Evidence package builder, Gemini call, JSON validation | Gemini computing any metric |
| Prompt versioning, guardrails, storage, review status | Pricing/margin advice (no cost data) |
| Cost control, caching | RAG, vector DB, fine-tuning |
Code: src/revint/ai/evidence.py (the ONLY path to Gemini),
src/revint/ai/prompts/, src/revint/ai/client.py.

## 2. Inputs and outputs
| Kind | Name |
|---|---|
| In | `opp_opportunities`, `opp_evidence`, config |
| Out | `app_ai_outputs` in app.duckdb (never the warehouse) |
| Env | `GEMINI_API_KEY` in .env (server-side only) |
| CLI | `revint ai generate --opp <id>` / `--top <n>` |

## 3. Evidence package (FR-A1)
Built only by `evidence.py` from `opp_evidence`. Pydantic model
`EvidencePackage`, serialised JSON, hashed (`evidence_hash`).

| Field | Content |
|---|---|
| `opp_id`, `type`, `as_of_date`, `algo_version` | identity |
| `entity` | masked customer label (e.g. `Customer C-0042`), branch, channel |
| `facts[]` | `{id, label, value, unit, definition}` measured by SQL |
| `estimate` | value range and method (marked Estimate) |
| `peer_context` | peer group size, penetration (aggregates only) |
| `data_quality_notes[]` | flags affecting this entity |
| `net_sales_definition` | field name, "provisional" |

Rules: max `ai.max_facts` facts (default 15); no raw lines, no
names, no codes while `ai.mask_identifiers` is true (default true);
masking map kept in app.duckdb, never sent. A test asserts that no
transaction-level field names appear in a package.

## 4. Response schema (FR-A2)
Pydantic `AiBrief`, validated; Gemini called with a JSON response
schema.

| Field | Type / constraint |
|---|---|
| `headline` | string, <= 120 chars |
| `explanation` | string, <= 600 chars |
| `recommendation` | string |
| `actions[]` | 1-5 items: `{text, suggested_owner_role, evidence_ids[]}` |
| `risks[]` | 0-4 strings |
| `confidence_label` | enum High / Medium / Low |
| `evidence_ids_used[]` | subset of package fact ids |

## 5. Guardrails (FR-A3)
| ID | Rule |
|---|---|
| G1 | Prompt forbids new numbers, causes, percentages, pricing or margin advice |
| G2 | Post-check: every number in the output text must match a fact value in the package (formatted variants allowed); otherwise reject |
| G3 | `evidence_ids` must exist in package; unknown id rejects |
| G4 | Invalid JSON or schema failure: retry up to `ai.max_retries` (default 2), then store status `failed`, never partial text |
| G5 | `confidence_label` cannot exceed the engine's confidence |
| G6 | Banned-term check (price cut, discount, margin, because of [competitor/macro]) rejects |
| G7 | Timeouts and quota errors do not break the app; UI shows the measured evidence without AI |

## 6. Prompts and versioning
- Files: src/revint/ai/prompts/<name>.v<N>.md; one per opp type plus system prompt.
- `prompt_version` = filename stem + content hash; changing a prompt
  requires a new version file.
- Model name from config (`ai.model`, default [x] e.g. a Gemini Flash
  model; confirm availability).
- Temperature `ai.temperature` default 0.2.

## 7. Storage (FR-A4)
`app_ai_outputs`: `output_id`, `opp_id`, `evidence_json`,
`evidence_hash`, `model`, `prompt_version`, `generated_at`,
`response_json`, `validation_status`, `review_status`
(Draft / Reviewed / Approved / Rejected), `reviewed_by`,
`reviewed_at`, `token_in`, `token_out`.
Approved outputs are immutable: regenerate creates a NEW row and
never overwrites, and only on explicit request.

## 8. Cost and caching
- Cache key = `evidence_hash` + `prompt_version` + `model`. Hit means no call.
- Generate on demand and for top `ai.precompute_top_n` (default 20) per run.
- Token counts stored; `ai.daily_call_limit` (default 200).
- Batch run prints counts only (no content) in logs.

## 9. UI labelling (FR-A5)
Measured fact (from `facts`), Estimate (value range), AI suggestion
(everything from Gemini) are three visually and textually distinct
blocks (spec 07).

## 10. Acceptance-level checks
- [ ] Package for a fixture contains no raw rows, names or codes when masking on
- [ ] Fake Gemini client: valid JSON stored with all provenance fields
- [ ] Output with an invented number is rejected (G2)
- [ ] Unknown evidence id rejected (G3); invalid JSON retries then `failed`
- [ ] Same evidence/prompt/model hits cache; changed evidence does not
- [ ] Approved output not overwritten by regeneration
- [ ] No API key in repo, logs or responses; tests run without network

## 11. Dependencies
Specs 03 (evidence), 10 (secrets, config), 09 (app.duckdb shared
conventions). Feeds 06, 08.

## 12. OPEN QUESTIONS
- OPEN QUESTION: Permission to send evidence to an external AI
  service. Default: mask identifiers, send aggregates only; no calls
  at all until permission is recorded in decisions.md
  (`ai.enabled: false` until then; fake client in tests/demo). Why:
  decisions.md lists it as open.
- OPEN QUESTION: Which Gemini model and via which endpoint (public API
  or company Vertex)? Default: [x] via google-genai, configurable. Why:
  corporate policy unknown.
- OPEN QUESTION: Language of output? Default: English. Why: not stated.
- OPEN QUESTION: Who reviews AI output (review_status)? Default: sales
  manager role. Why: process not defined.
