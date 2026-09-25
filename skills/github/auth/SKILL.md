---
namespace = "github"
name = "auth"
version = "1.0.0"
capabilities = ["auth", "credentials"]
trigger_patterns = ["github auth", "gh login", "token setup", "permission denied"]
applicable_agents = ["coding", "general"]
dependencies = {}
contract = { inputs = { task = { type = "str", required = true } }, outputs = { guidance = { type = "str" } } }
self_tests = [{ match = { task = 'smoke' }, not_match = { task = 123 } }]
---
# github/auth

No auth, no GitHub. Run the detection flow FIRST on any machine before
`github/code-review`, `github/pr-workflow`, or `github/issues` — those
skills assume this one already passed.

## Trigger

Use when: `gh auth status` fails, pushes get 403/permission-denied, a new
machine or worker needs GitHub access, or `gh repo create` returns
"Resource not accessible".

## 1. Detect (30 seconds)

```bash
git --version
gh --version 2>/dev/null || echo "gh not installed"
gh auth status 2>/dev/null || echo "gh not authenticated"
```

Decision: `gh` authenticated → use `gh` for everything. `gh` present but
logged out → token login below. No `gh` → HTTPS-token or SSH path.

## 2. gh login

Interactive: `gh auth login` (HTTPS + browser). Headless/workers:
`echo "$TOKEN" | gh auth login --with-token` then `gh auth setup-git`.
Windows: `winget install --id GitHub.cli`; open a FRESH shell after install
(PATH refresh). Verify: `gh auth status`.

## 3. Token rules (the gotchas that waste hours)

- **Classic PAT** (`repo` + `workflow` scopes) for anything that creates
  repos — fine-grained PATs CANNOT create repositories unless the
  account-level "Repository creation" permission is explicitly granted
  (403 otherwise).
- Token as password, never the GitHub password. `GITHUB_TOKEN` env for API
  calls; credential helper `store` (persistent) or `cache --timeout=28800`.
- Headless agents: write `https://<user>:<token>@github.com` to
  `~/.git-credentials` directly instead of waiting on a prompt that never
  comes. SSH alternative: ed25519 key + `git@github.com`, test with
  `ssh -T git@github.com`.

## 4. J5 secrets hygiene (non-negotiable)

Tokens live in env/keyring ONLY. Never in the InterHarness bus, never in
ledger files, never in repos, never in logs. `secretscan` gates every
commit; a leaked token is rotated immediately, not "later".

## 5. Troubleshooting (first checks)

Password prompt loop → use a token, not a password. `Permission denied` →
scope check. Stale cached creds → `git credential reject` + re-auth.
`gh` missing after winget → new shell or full path under
`C:\Program Files\GitHub CLI\`.

## Verify before use

- [ ] `gh auth status` (or `git ls-remote`) succeeds non-interactively.
- [ ] `repo` scope present if pushing/creating; `workflow` if touching Actions.
- [ ] No token material in files, logs, or bus messages.

## Source

Adapted from `evsphereofficial/elevia-skills` ([MIT](https://github.com/evsphereofficial/elevia-skills)):
`github/github-auth.md` v1.2.0. J5 additions: secrets-hygiene section tied
to `secretscan`, headless-worker rules, Windows-first ordering.
