---
namespace = "github"
name = "repo-management"
version = "1.0.0"
capabilities = ["repos", "hygiene"]
trigger_patterns = ["create repo", "pre-publish", "clone repo", "hygiene gate"]
applicable_agents = ["coding", "general"]
dependencies = {}
contract = { inputs = { task = { type = "str", required = true } }, outputs = { guidance = { type = "str" } } }
self_tests = [{ match = { task = 'smoke' }, not_match = { task = 123 } }]
---
# github/repo-management

Repos are created once and regretted forever unless gated. This skill is the
gate: clone/create/fork mechanics plus the pre-publish hygiene checklist that
runs before anything goes public.

## Trigger

Use when: bringing a project onto GitHub, forking, auditing a repo before
first push, or cleaning a dirty tree (data files, secrets, junk).

## 1. Clone / create / fork

```bash
git clone https://github.com/owner/repo.git ./dir   # or --depth 1, --branch X
gh repo clone owner/repo
gh repo create <name> --public --description "..." --push --source . --remote origin
```

## 2. Pre-publish hygiene gate (ALL must pass)

1. **`.gitignore` present**: artifacts (`__pycache__`, `*.pyc`, `.venv`,
   `node_modules`, `dist`, `build`), data (`*.csv/parquet`, weights
   `*.pt/*.safetensors`), session state (`.swarm/`, caches, logs), secrets
   (`.env`, `*.pem`).
2. **Tracked junk removed**: `git rm --cached` for anything the new ignore
   covers (`.bak`, logs, caches already committed by accident).
3. **Secrets sweep**: `secretscan` + pattern grep (`sk-`, `ghp_`, `AKIA`,
   `api_key\s*[:=]`) — zero findings or STOP.
4. **Staged-set review**: `git status --porcelain` + `git diff --cached
   --stat` — every staged file intentional, no surprises.
5. **LICENSE chosen deliberately**: PolyForm Noncommercial for monetizable
   work (commercial contact inside), MIT for throwaway utilities. The
   choice is a business decision, not a default.
6. **Commit message** describes the change; push; verify remote state.

Fork reuse: change remote to the new repo (`remote remove origin` + `add`),
keep upstream LICENSE + attribution, untrack data dirs.

## 3. Remotes & identity

Owner/repo derived from `git remote get-url origin` (strip to `owner/repo`).
Commits need `user.name`/`user.email` — agent commits use the project
identity, never a personal one by accident.

## Verify before use

- [ ] Hygiene gate 1–6 all green, evidenced (scan output quoted).
- [ ] Staged set reviewed file-by-file, not `git add -A` blind.
- [ ] Remote URL + visibility (public/private) confirmed before push.

## Source

Adapted from `evsphereofficial/elevia-skills` ([MIT](https://github.com/evsphereofficial/elevia-skills)):
`github/github-repo-management.md` v1.1.0. J5 additions: hygiene gate as a
blocking checklist, LICENSE-as-business-decision, staged-set review rule.
