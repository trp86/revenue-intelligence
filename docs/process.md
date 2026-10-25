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

## Project references
- Repo: tpradha/revenue-intelligence (company GitHub:
  git.t3.daimlertruck.com)
- Project board: number 1, owner tpradha
- Labels: epic, story, bug, blocked, data, sql, ai, api,
  frontend, infra