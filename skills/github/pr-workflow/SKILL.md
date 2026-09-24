---
name: github/pr-workflow
description: >-
  Full PR lifecycle: branch, commit, open, watch CI, auto-fix failures, merge.
  Input: change description + base branch. Output: merged PR URL or blocked state.
---

# github/pr-workflow

Branch → commit → push → PR → CI green → merge. `gh` first, REST fallback.
Conventional Commits throughout (`feat|fix|refactor|docs|test|ci|chore|perf`).

## Trigger

Use when: shipping any change as a PR, monitoring CI, fixing red checks, or
merging. Pairs with `github/code-review` (review before merge).

## 1. Branch + commit

```bash
git checkout main && git pull origin main
git checkout -b feat/short-description          # feat|fix|refactor|docs|ci
git add <specific-files>                        # never `git add -A` blind
git commit -m "feat: short description

- What changed and why (wrap at 72)"
git push -u origin HEAD
```

## 2. Open the PR

```bash
gh pr create --title "feat: ..." --body "## Summary
...what + why...

## Test Plan
- [ ] suite green
" --draft   # drop --draft when ready
```

## 3. Watch CI

```bash
gh pr checks              # one-shot
gh pr checks --watch      # poll until done
gh run list --branch $(git branch --show-current) --limit 5
gh run view <RUN_ID> --log-failed
```

## 4. Auto-fix loop (max 3 attempts, then escalate to the user)

1. Identify failures from checks/logs. 2. Read code, fix with file tools.
3. Commit `fix: ...`, push. 4. Re-check CI. Repeat ≤3×, then stop and report —
   never loop forever on red.

## 5. Merge (squash + delete branch)

```bash
gh pr merge --squash --delete-branch
# or arm it: gh pr merge --auto --squash --delete-branch
```

## Verify before use

- [ ] Branch cut from fresh `main`, name follows convention.
- [ ] Staged files reviewed (no secrets, no junk) before commit.
- [ ] CI green (or explicitly waived with reason) before merge.
- [ ] Auto-fix loop bounded (3 attempts max).

## Source

Adapted from `evsphereofficial/elevia-skills` ([MIT](https://github.com/evsphereofficial/elevia-skills)):
`github/github-pr-workflow.md` v1.1.0. J5 additions: 3-attempt bound as a
hard rule, staged-file review gate, Windows notes.
