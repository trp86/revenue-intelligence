---
description: Draft user stories for an epic (usage: /draft-stories <epic issue number>)
argument-hint: <epic issue number>
---

Read epic #$ARGUMENTS, its spec in docs/specs, docs/decisions.md and
docs/process.md. Do not write code.

Propose user stories for this epic as a list first: title, one-line
story, dependencies, acceptance criteria (Given/When/Then, testable),
out of scope. Each story must fit one PR. Show me the list and wait
for approval.

After I approve, create each story with `gh issue create` using the
story template, label `story`, add it to project 1, make it a
sub-issue of the epic if supported, and leave it in Backlog. Never
put anything in Ready.