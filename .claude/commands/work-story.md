---
description: Implement a Ready GitHub story end to end (usage: /work-story <issue number>)
argument-hint: <issue number>
---

Work on story #$ARGUMENTS following docs/process.md and CLAUDE.md.

1. Set the environment: `$env:GH_HOST = "git.t3.daimlertruck.com"`.
2. Read the issue: `gh issue view $ARGUMENTS --comments`. Read the
   linked spec section, the parent epic, and any dependency issues.
3. Check the board: the item must be in Ready. If it is not, stop
   and tell me. If any dependency is not Done, stop and tell me.
4. Check the Definition of Ready. If any acceptance criterion is
   ambiguous or a business question is open, post your questions as
   an issue comment and STOP.
5. Create branch `story/$ARGUMENTS-<short-name>` from an up-to-date
   main. Move the board item to "In progress".
6. Write failing tests derived from each acceptance criterion
   first, then implement until they pass.
7. Run the tests, ruff and sqlfluff. Fix until all are green. Do not
   skip or weaken tests.
8. Update docs or the data dictionary if the story affects them.
9. Comment on the issue with: what changed, files touched, and
   evidence for each acceptance criterion (test names and aggregate
   numbers only, no customer-level data). Tick the criteria that
   are met in the issue body. If one is not met, say so plainly.
10. Commit with messages starting "#$ARGUMENTS", push the branch,
    open a PR whose body says "Closes #$ARGUMENTS" and links the
    evidence comment. Move the board item to "In review".
11. Do not merge. Report a short summary and anything I should
    review closely, plus any new issues you logged for out-of-scope
    findings.