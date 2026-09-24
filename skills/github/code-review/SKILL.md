---
name: github/code-review
description: >-
  End-to-end code review: local diffs, PR checkout, inline comments, formal
  verdicts via gh (curl fallback). Input: diff_sha or PR number. Output:
  P0/P1/P2 findings with file:line evidence, then approve/request-changes.
---

# github/code-review

Review local changes pre-push or open PRs, and post the verdict back to
GitHub. `gh` first, plain `git` + REST fallback where `gh` is absent.

## Trigger

Use when: reviewer must audit a diff or PR, a delegation leaf needs
verification against a remote branch, or findings must land as inline PR
comments (not just chat text).

## Auth

Prefer `gh auth status`; else `GITHUB_TOKEN` env (never hardcode; never log).
Derive `OWNER/REPO` from `git remote get-url origin` (strip to `owner/repo`).

## 1. Local review (pre-push, pure git)

```bash
git diff main...HEAD --stat            # scope first
git log main..HEAD --oneline           # what changed, per commit
git diff main...HEAD -- <file>         # file-by-file for full context
git diff main...HEAD | grep -n "print(\|console\.log\|TODO\|FIXME\|HACK\|debugger"
git diff main...HEAD | grep -in "password\|secret\|api_key\|token.*=\|private_key"
git diff main...HEAD | grep -n "<<<<<<\|>>>>>>\|======="
```

## 2. PR review

```bash
gh pr view 123; gh pr diff 123 --name-only; gh pr checks 123
git fetch origin pull/123/head:pr-123 && git checkout pr-123   # full local context
# ... review, run tests ...
git checkout main; git branch -D pr-123                        # clean up after
```

Inline comment (needs head SHA + path + line, `side: RIGHT` for new code):
```bash
HEAD_SHA=$(gh pr view 123 --json headRefOid --jq '.headRefOid')
gh api repos/$OWNER/$REPO/pulls/123/comments --method POST \
  -f body="..." -f path="src/auth/login.py" -f commit_id="$HEAD_SHA" -f line=45 -f side="RIGHT"
```

Formal verdicts: `gh pr review 123 --approve|--request-changes|--comment --body "..."`.
Atomic multi-comment review via `POST .../pulls/N/reviews` with
`{"commit_id","event":"APPROVE|REQUEST_CHANGES|COMMENT","comments":[...]}`.

## 3. Checklist (every review, both modes)

Correctness (edge cases, error paths) · Security (secrets, injection, authz) ·
Quality (naming, DRY, single responsibility) · Testing (new paths, happy +
error cases) · Performance (N+1, blocking calls) · Docs (public APIs, why).

## 4. J5 output contract (extends `review-checklist`)

Findings MUST be emittable as J5 receipts: `path:line` + 1-line quote +
severity **P0** (blocks merge) / **P1** (must acknowledge) / **P2** (nit).
Post the same content as the PR summary comment so chat and GitHub agree.
Approve only with zero P0/P1 open; request-changes otherwise.

## Verify before use

- [ ] Findings carry file:line evidence, never vibes.
- [ ] Secrets/keys/TODO sweep run on the actual diff, not memory.
- [ ] PR branch checked out locally for anything beyond trivia.
- [ ] Cleanup branch after (`checkout main`, delete `pr-N`).

## Source

Adapted from `evsphereofficial/elevia-skills` ([MIT](https://github.com/evsphereofficial/elevia-skills)):
`github/github-code-review.md` v1.1.0. J5 additions: P0/P1/P2 receipt mapping,
Windows/`gh.exe` notes, cleanup discipline.
