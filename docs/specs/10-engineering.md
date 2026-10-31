# 10 Engineering (Epic E0)

Status: DRAFT. Repo, tooling, config, CLI, testing, CI, secrets.

## 1. Purpose and scope
| In | Out |
|---|---|
| Repo layout, uv project, config, CLI, test/lint/CI, secrets | Deployment, hosting, containers (POC runs locally) |
| Pipeline runner for numbered SQL | Any business logic |

## 2. Repo layout
```
config/settings.yaml      business decisions and thresholds
config/definitions.yaml   metric definitions shown in UI
config/explore.yaml       allow-list for the query layer
data/                     git-ignored (raw, bronze, warehouse, app.duckdb)
docs/                     decisions, process, requirements, specs
sql/10_silver/ 20_gold/ 30_opportunities/ checks/   numbered, run in order
src/revint/ingest|pipeline|query|ai|api|backtest|cli
tests/                    pytest (unit, sql, api)
frontend/                 React app
.github/                  workflows, issue templates
.env.example              names only, no values
```

## 3. Tooling
| Area | Choice |
|---|---|
| Python | 3.12+, managed by uv (`uv sync`) |
| Libraries | polars, duckdb, fastapi, pydantic, typer, google-genai, pytest, ruff, sqlfluff |
| Commands | `uv run pytest`, `uv run ruff check .`, `uv run sqlfluff lint sql`, `uv run revint build all` |
| Frontend | `cd frontend; npm install; npm run dev` (Windows PowerShell) |

## 4. Configuration (config/settings.yaml)
- Loaded into a pydantic `Settings` model; unknown keys fail; every key has a documented default.
- Sections: `paths`, `ingest`, `labels`, `net_sales`, `void`, `duplicates`, `peer_groups`, `recovery`, `dormancy`, `whitespace`, `crosssell`, `scoring`, `value`, `backtest`, `ai`, `assistant`, `explore`, `api`, `actions`, `recon`, `asof`.
- `asof.date` default `2020-02-29`.
- `paths` and `asof` are required; every other section may be left out of the file and then takes its documented defaults. Within a section an unknown key fails and an out-of-range value fails naming the key.
- `duplicates.key_columns`, when unset, is derived as `ingest.expected_columns` minus `_source_row` (`Settings.duplicate_key_columns`).
- Business-decision changes happen through PR (process.md rule 7).
- Env overrides only for paths and secrets, never thresholds.
- Config hash computed and stored with each build and each backtest run. It covers the business sections only; `paths` is excluded because it is machine-specific.
- `paths.reports` (default `reports`, git-ignored) is the only optional path: generated reports go there. Relative `paths` resolve against the project root. Env overrides use `REVINT_PATHS_<KEY>` (for example `REVINT_PATHS_RAW`); no other key is read from the environment.
- Every section added to `Settings` ships with its own test module `tests/unit/test_settings_<section>.py`; a test fails if a section has none.

## 5. CLI (typer, `revint`)
| Command | Does |
|---|---|
| `revint build bronze|silver|gold|all` | Run stages; `all` builds raw to gold |
| `revint check` | SQL checks and reconciliation |
| `revint report dq` | Write the data quality report |
| `revint opportunities build [--as-of]` | Engines (spec 03) |
| `revint backtest run|report` | Spec 04 |
| `revint ai generate` | Spec 05 |
| `revint app init` | Create app.duckdb |
| `revint serve` | Start API |
Until the epic that owns a command implements it, the command is a stub: it validates the settings, prints "not implemented" and exits with code 3 without doing any work. Exit code 1 means invalid or missing settings; `--help` needs no settings.
The runner is `revint.pipeline.run_stage(stage_dir, settings)` (`execute_stage` wraps it for the command line). A stage is one folder of `.sql` files (for example `sql/10_silver`); only `*.sql` files directly in the folder run, in filename order, inside one DuckDB transaction. Before anything runs, every file is parsed and its parameters checked, so a syntax error or a missing parameter fails the stage without touching the warehouse. Failures name the file and statement number, never SQL text, and DuckDB messages have quoted values masked. Exit codes: 4 stage failed, 5 warehouse file in use by another process. `revint build bronze` is implemented (story #33, `revint.ingest.bronze`); it exits 4 when the bronze build fails and 6 when a raw workbook is open in Excel or locked. `revint report dq` is implemented (story #42, `revint.report`, exit 4 when the warehouse or quality tables are missing). `revint check` is implemented (story #43, `revint.recon`): it runs `sql/checks` (R1 to R4, R7 silver side, R8) and exits 7 when a reconciliation check fails. `revint build silver` and `revint build all` are implemented (story #45, `revint.build` and `revint.silver.execute_silver`): `build silver` needs the bronze file (it never reads the raw folder) and exits 4 with a message telling the user to run `revint build bronze` when it is missing; `build all` runs bronze then silver, stops at the first stage that fails (its exit code is the stage's: 4, 5 or 6) and ends by stating that no gold stage exists yet. Every stage run, `build bronze` included, is recorded in `build_log`. A silver re-run gives the same content apart from the `silver_excluded_rows.excluded_at` time, and never changes a bronze file. `build gold` is still a stub (exit 3).
SQL files use named parameters written `$name`, taken from `Settings` as `<section>_<key>` (for example `$asof_date`, `$void_blank_means`, `$net_sales_field`, `$recon_tolerance_amount`). `paths` and mappings are not parameters, and `$duplicates_key_columns` is the derived list from `Settings.duplicate_key_columns`. A settings mapping is not itself a parameter: it arrives as two lists in the same order, `$<name>_keys` and `$<name>_values` (for example `$void_value_map_keys` and `$void_value_map_values`), which SQL joins with `unnest`, so a key is always data. A caller can add parameters `Settings` does not know, such as `$bronze_file` for the silver stage (`run_stage(..., extra_parameters=...)`); a name that a settings parameter already uses is refused. The SQL linter binds stand-in values for every parameter in `.sqlfluff` (placeholder templater), so a SQL file that uses a new parameter adds a line there. A parameter a file names that does not exist fails the stage naming it. A new settings section is available to SQL with no runner change.
Rules: SQL files run in filename order inside one DuckDB transaction per
stage; failure stops the stage and prints the failing file; stage run
records written to `build_log` (counts, durations, config hash).

`build_log` (story #30, `revint.build_log`) is a table in the warehouse file with one row per stage run: `run_id`, `stage`, `status` (`succeeded` or `failed`), `started_at` (UTC), `duration_seconds`, `files`, `statements`, `rows_out` (counts; NULL when unknown, and `files`, `statements` and `rows_out` are NULL for a failed stage), `failed_file` (the SQL file named by the error, else NULL) and `config_hash` (the hash of the business settings, `paths` excluded, so a changed setting changes it). `run_logged(settings, stage, run, to_counts)` wraps a stage, records the row whether it succeeds or fails, and re-raises the stage's own error unchanged. The table is written only by this module, never by stage SQL, so rebuilding a stage keeps the earlier rows; rows are only added. No message, row value or SQL text is stored or logged. If the row cannot be written after a success, `BuildLogError` is raised; after a failure the stage's own error is raised and a warning is logged. The build commands call it (story #45).

## 6. Testing
| Layer | How |
|---|---|
| Unit | pytest, small synthetic fixtures committed under tests/fixtures (no client data) |
| SQL checks | files in sql/checks, each returns zero rows when OK; run via pytest |
| Real-data checks | marked `@pytest.mark.realdata`, skipped if data/ absent, never in CI |
| API | FastAPI TestClient; AI uses a fake client |
| Frontend | Vitest + Testing Library, Playwright walkthrough, axe |
Every acceptance criterion maps to at least one named test.

## 7. CI (GitHub Actions on company GitHub)
- On PR: `uv sync`, ruff, sqlfluff, pytest (without realdata), frontend lint/type-check/test/build, OpenAPI drift.
- No network calls to Gemini; no secrets needed.
- Required to pass before a human merges. [x] runner availability on the enterprise host.
- No runner exists on the host yet, so `ci.yml` runs on `workflow_dispatch` only and `uv run revint-gate` (`src/revint/gate.py`) runs the same checks locally; see docs/process.md. The command list lives in `gate.CHECK_STEPS`, and a test asserts `ci.yml` runs exactly those commands. Restoring the `pull_request` trigger is tracked in issue #27.
- A secret-scan step (e.g. gitleaks) [x] if available.

## 8. Secrets and safety
- `.env` git-ignored; `.env.example` lists names (`GEMINI_API_KEY`).
- Pre-commit/CI check fails on files under data/ or on `.env`.
- Logs: counts and aggregates only; never customer-level values; test with a log-capture check.
- Never write under data/raw (guard in code: raw opened read-only; test).
- Dependencies pinned by `uv.lock`.
- Guards live in `src/revint/guards.py` (tracked files under `data/`, tracked `.env`, non-empty values in `.env.example`) and are enforced by `tests/unit/test_guards.py`, which CI runs.
- Raw files are opened only through `revint.ingest.raw.open_raw`: binary read-only, no mode argument, paths outside `paths.raw` refused. It logs sizes and counts only.

## 9. Edge cases
- Windows paths and PowerShell quoting; use `pathlib`, no shell-specific scripts in code.
- Excel file locked/open: clear error.
- DuckDB file locked by API while CLI builds: detect and tell the user.
- Missing config key: fail with key name.

## 10. Acceptance-level checks
- [ ] Fresh clone: `uv sync` and `uv run pytest` pass without data/
- [ ] Settings with an unknown key fails validation (test)
- [ ] `revint build all` runs stages in order; stops on failing SQL (test with a bad file)
- [ ] Config change of a threshold needs no code edit (cross-checked by spec 03)
- [ ] CI workflow runs the commands above
- [ ] Guard test: no write to data/raw; no tracked files under data/
- [ ] `.env.example` has no real values

## 11. Dependencies
Spec 00. Everything depends on this; E0 stories come first.

## 12. OPEN QUESTIONS
- OPEN QUESTION: CI runner and gitleaks availability on git.t3.daimlertruck.com. Default: GitHub Actions workflow with standard runners; confirm. Why: enterprise hosts differ.
- OPEN QUESTION: Package index access (uv/npm behind a corporate proxy)? Default: assume reachable. Why: unknown.
- OPEN QUESTION: Warehouse file name/location. Default: `data/warehouse.duckdb`. Why: only app.duckdb is named in docs.
- OPEN QUESTION: Source Excel on shared drive or local only? Default: local `data/raw`. Why: CLAUDE.md says data/raw.
