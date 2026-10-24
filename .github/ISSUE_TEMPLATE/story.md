---
name: User story
about: A small unit of work for one PR
labels: story
---

## Story
As a [role], I want [capability], so that [value].

## Context
- Spec: docs/specs/<file>.md#<section>
- Epic: #
- Depends on: #

## Acceptance criteria
- [ ] AC1: Given ..., when ..., then ...
- [ ] AC2: Given ..., when ..., then ...
- [ ] AC3: Automated tests cover AC1 and AC2

## Out of scope
-

## Technical notes
(Expected files, tables, config keys, SQL layer)

## Definition of Ready (author checks before moving to Ready)
- [ ] Linked to spec and epic
- [ ] Acceptance criteria are testable
- [ ] Dependencies are done
- [ ] Out of scope is stated
- [ ] Small enough for one PR
- [ ] No open business questions

## Definition of Done (Claude Code checks)
- [ ] All acceptance criteria met, with evidence in a comment
- [ ] Tests pass
- [ ] Lint passes (ruff, sqlfluff)
- [ ] Docs updated if affected
- [ ] PR opened with "Closes #n"
