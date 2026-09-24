---
name: github/issues
description: >-
  GitHub issue lifecycle: list, triage, create with templates, label,
  assign, comment, close. Input: issue number or report. Output: updated
  issue state.
---

# github/issues

Issues are the intake queue. List → triage → create well-formed → label →
assign → track → close. `gh` first, REST fallback.

## Trigger

Use when: filing bugs/features from findings, triaging a backlog, tracking
work items for a delegation batch, or commenting status updates.

## 1. List & triage

```bash
gh issue list --state open --label "bug"
gh issue view 42
```

Triage every open issue exactly once: reproduce-or-close (bugs need repro
steps or they get `needs-repro`), label (`bug|feature|docs`, `priority:*`,
area), assign or leave unassigned deliberately. Stale (>90d, no activity,
no owner): comment asking status, close after no reply — never silently.

## 2. Create (templates required)

Bug: Description / Steps to Reproduce / Expected / Actual / Environment
(OS, version). Feature: Description / Motivation / Proposed solution /
Alternatives considered.

```bash
gh issue create --title "..." --body "..." --label "bug,backend"
```

## 3. Manage

```bash
gh issue edit 42 --add-label "priority:high" --remove-label "needs-triage"
gh issue edit 42 --add-assignee username
gh issue comment 42 --body "Root cause in auth middleware. Fix in progress."
gh issue close 42 --reason completed   # completed|not planned (+ comment why)
gh issue reopen 42                     # regressions reopen, never duplicate
```

REST equivalents live under `/repos/$OWNER/$REPO/issues[/N][/labels|/assignees|/comments]`
with `{"title","body","labels":[],"assignees":[]}` payloads.

## Verify before use

- [ ] New issues use the bug/feature template (no blank bodies).
- [ ] Every triaged issue has labels + owner-or-deliberately-unassigned.
- [ ] Close reason stated; regressions reopen the original issue.

## Source

Adapted from `evsphereofficial/elevia-skills` ([MIT](https://github.com/evsphereofficial/elevia-skills)):
`github/github-issues.md` v1.1.0. J5 additions: triage-once rule, stale
policy, reopen-instead-of-duplicate rule.
