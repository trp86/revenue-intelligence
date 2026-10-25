# CLAUDE.md

Project: revenue-intelligence (POC for sales managers).
Read first: docs/decisions.md, docs/process.md, docs/requirements.md,
and the relevant file in docs/specs/.

## Hard rules
1. Work ONLY on a GitHub issue that is in "Ready" on the project
   board. If no issue is named, list the Ready issues and ask.
2. Never merge a PR. Never push to main. Never expand scope: log
   extra findings as new issues in Backlog.
3. If an acceptance criterion is ambiguous, STOP and ask in an
   issue comment. Do not guess.
4. Never commit data, secrets or .env. data/ is git-ignored. Never
   print customer-level data into issues, PRs or logs; use counts
   and aggregates in evidence.
5. Never send raw transactions to Gemini. Only the small evidence
   package built by src/revint/ai/evidence.py.
6. Business decisions (net sales field, thresholds, peer groups,
   as-of date) live in config/settings.yaml. Never hard-code them.
7. Do not delete or edit anything under data/raw, and never modify
   bronze. Flag bad rows, never drop them. The only exclusions
   allowed are the documented stray row and exact duplicates. They
   are marked in silver (is_excluded, never deleted: silver keeps
   every bronze row), recorded in silver_excluded_rows, and omitted
   from gold. Never in bronze or data/raw.

## GitHub environment
- Company GitHub Enterprise: set `$env:GH_HOST =
  "git.t3.daimlertruck.com"` in every new PowerShell session.
- Repo: tpradha/revenue-intelligence. Project board: number 1,
  owner tpradha.
- Use `gh` for issues, PRs and the board. Discover board field and
  option ids with `gh project field-list 1 --owner tpradha` and
  item ids with `gh project item-list 1 --owner tpradha --format
  json`; do not hard-code ids.

## Architecture (see docs/decisions.md)
- Bronze: Polars reads Excel -> Parquet (data/bronze), all text,
  lineage columns.
- Silver and gold: DuckDB SQL files in sql/, numbered, run in order
  by src/revint/pipeline. Python only where SQL is awkward.
- Net sales is defined once in one view, driven by config.
- App state (AI output, actions) in data/app.duckdb, never in the
  warehouse file.
- AI: Python/SQL calculates, Gemini communicates. Schema-validated
  JSON, versioned prompts in src/revint/ai/prompts, store evidence
  snapshot + model + prompt version + timestamp.
- API: FastAPI. Frontend (React) calls the API only, never DuckDB
  or Gemini.

## Commands (Windows, PowerShell)
- Setup: `uv sync`
- Tests: `uv run pytest`
- Lint: `uv run ruff check .` and `uv run sqlfluff lint sql`
- Build: `uv run revint build all`
- Frontend: `cd frontend; npm install; npm run dev`
(If a command does not exist yet, create it as part of the story
that needs it.)

## Code standards
- Python 3.12+, type hints, pydantic models for contracts, small
  functions, no business logic in API routers.
- SQL: one purpose per file, lowercase keywords, CTEs, comments for
  every business rule, parameters from config.
- Tests: every acceptance criterion gets at least one test. SQL
  checks live in sql/checks and run via pytest.
- Frontend: TypeScript, design tokens only (no hard-coded colours),
  loading/empty/error states on every screen, colour is never the
  only signal, every number can show its definition.
- Commit messages: "#<issue> short description".

## Definition of Done
See docs/process.md. Do not mark a story done unless tests and lint
pass and each acceptance criterion has evidence in an issue comment.