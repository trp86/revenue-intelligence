# Way of working

## Hierarchy
Specs (docs/specs, in the repo) -> Epics (issue, label `epic`)
-> User stories (issue, label `story`, sub-issue of an epic)
-> Acceptance criteria (checkboxes inside the story).

## Board columns
Backlog -> Ready -> In progress -> In review -> Done
Blocked is used at any time when something external is needed.

## Rules
1. Only a human moves a story to **Ready**, after checking the
   Definition of Ready.
2. Claude Code works ONLY on stories in Ready. If none is named,
   it lists the Ready stories and asks which one.
3. One story = one branch = one PR.
4. Claude Code never merges. A human reviews and merges.
5. Scope never grows inside a story. Extra findings become new
   issues in Backlog.
6. If an acceptance criterion is ambiguous, Claude Code stops and
   asks in an issue comment instead of guessing.
7. Business decisions (net sales definition, customer identity,
   thresholds) are changed in config/settings.yaml or
   docs/decisions.md through a PR, never silently in code.

## Definition of Ready
- [ ] Linked to a spec section and an epic
- [ ] Clear "As a / I want / so that"
- [ ] Acceptance criteria are testable (Given/When/Then or
      measurable checks)
- [ ] Dependencies are listed and already Done
- [ ] Out of scope is stated
- [ ] Small enough for one PR (about a day or less)
- [ ] No open business question, or a documented default exists

## Definition of Done
- [ ] Every acceptance criterion met, with evidence in an issue
      comment (test name, query result or output)
- [ ] Tests pass
- [ ] Lint passes (ruff for Python, sqlfluff for SQL)
- [ ] `uv run revint-gate` passes (see "Checks while there is no CI runner")
- [ ] Docs and data dictionary updated if affected
- [ ] PR opened with "Closes #n", reviewed and merged by a human
- [ ] Board item moved to Done

## Claude Code workflow for a story
1. Read the issue and the linked spec section.
2. Create branch `story/<number>-short-name`; move item to
   In progress.
3. Write tests from the acceptance criteria first.
4. Implement.
5. Run tests and lint; fix until green.
6. Comment on the issue: what changed and evidence per criterion.
   Tick the criteria that are met.
7. Open a PR with "Closes #n"; move the item to In review.

## Checks while there is no CI runner
The company GitHub has no runner for this repo, so the CI workflow
(`.github/workflows/ci.yml`) is started by hand only and PRs show no
CI check. Until a runner exists (issue #27):
- `uv run revint-gate` runs the same checks as CI, in the same order:
  ruff, sqlfluff and pytest without `realdata`. It stops at the first
  failing step, names it, and exits non-zero.
- A passing `uv run revint-gate` is the evidence of green checks.
  The evidence comment on the story states that it was run and that it
  passed, with the pass counts.
- The reviewer can run the same command on the PR branch before
  merging.
- The tests run in parallel, one worker per CPU core (pytest-xdist, `-n auto` in
  `pyproject.toml`), so the command line is unchanged. Expect the whole gate to take
  about 6 to 7 minutes on an 8-core machine with nothing else running, down from about
  24 minutes in one process; fewer cores take longer, and a machine that is busy or
  asleep takes longer still. Each test builds in its own temporary folder and shares
  nothing with another. A test that writes into the repository (code, SQL, config, docs
  or tests) fails the run and the files are named. To run in one process, for example
  to use a debugger or read the output in order, use `uv run pytest -n 0 <path>`.
- When a runner exists, issue #27 restores the `pull_request`
  trigger and this section is removed.

## Faster loop for the POC deadline
Agreed on 2026-11-02 for the stories left (E5, E6, E7; docs/decisions.md section 11), until
the maintainer says otherwise:
- On each story branch, run the story's own tests plus `uv run ruff check .` and
  `uv run sqlfluff lint sql`. The evidence comment names the tests and the counts.
- Run the full `uv run revint-gate` once a day, before the day's PRs are merged, and post the
  result on one of them.
- Where an acceptance criterion leaves a choice open, use the proposed default, mark it
  provisional and list it in the PR for the maintainer, instead of stopping. A real business
  question (one the data or the specs cannot answer) still stops the story.
- Stories may be larger: about two or three per epic.
All the rules above still apply: Ready only, one branch and one PR per story, never merge,
never push to main, no customer-level data in issues, PRs or logs.

## Live Gemini check
Tests marked `live` call the real Gemini API. They run only with `REVINT_LIVE=1` and a
`GEMINI_API_KEY` (in the git-ignored `.env`): `REVINT_LIVE=1 uv run pytest -m live -n 0`. They are
skipped otherwise, so the gate never calls Gemini, and they assert the status only.

## Real-file checks
Tests marked `realdata` need the client workbooks under `data/raw` and a
built `data/bronze` (`uv run revint build bronze`). They are skipped when
`data/` is absent, are not part of `revint-gate`, and never run in CI.
Run them on the machine that holds the data before closing an epic:
`uv run pytest -m realdata`. They work on a copy of bronze with a
temporary warehouse, change nothing under `data/`, and assert counts, sums
and structure only. Evidence posted from them is counts and aggregates.

## Project references
- Repo: tpradha/revenue-intelligence (company GitHub:
  git.t3.daimlertruck.com)
- Project board: number 1, owner tpradha
- Labels: epic, story, bug, blocked, data, sql, ai, api,
  frontend, infra