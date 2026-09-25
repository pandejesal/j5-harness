---
namespace = "github"
name = "project-publishing"
version = "1.0.0"
capabilities = ["publishing", "portfolio"]
trigger_patterns = ["publish project", "repo worthiness", "profile readme", "portfolio"]
applicable_agents = ["coding", "general"]
dependencies = {}
contract = { inputs = { task = { type = "str", required = true } }, outputs = { guidance = { type = "str" } } }
self_tests = [{ match = { task = 'smoke' }, not_match = { task = 123 } }]
---
# github/project-publishing

Turn a folder of projects into a portfolio. Survey everything, publish what
earns it, skip the rest — and clean before creating, never after.

## Trigger

Use when: publishing a batch of projects, auditing what deserves a repo, or
maintaining profile presence.

## 1. Survey

Per directory record: has `.git`? has remote? file count, LOC estimate,
languages. One line each — triage from the table, not from memory.

## 2. Worthiness triage

| Publish | Skip |
|---|---|
| 500+ LOC of original, structured, runnable work | <100 LOC scraps, forks without changes |
| Coherent purpose a stranger could use | Model weights / data dumps alone |
| Complete (docs + entry point) | Throwaway experiments |

Forks with heavy modifications get a NEW repo (not the fork): untrack data,
commit the delta, change remote, push, keep upstream LICENSE + credit.

## 3. Clean → README → create → push

Clean per `github/repo-management` hygiene gate (gitignore, untracked junk,
secrets sweep). README needs: one-liner, description, stack, quickstart,
structure. Then `gh repo create <name> --public --description "..." --push
--source .`. Token needs `repo` scope (classic PAT) or the fine-grained
"Repository creation" account permission — otherwise 403.

## 4. Profile (after publishing)

Repo descriptions one line each; profile README (`<user>/<user>`) with intro,
key-project table, stack, contact. Pins are web-UI only (no API) — guide,
don't attempt.

## Verify before use

- [ ] Worthiness table filled per candidate (publish/skip + reason).
- [ ] Hygiene gate green before `gh repo create`, not after.
- [ ] Description + topics set at creation (retrofitting is forgotten work).

## Source

Adapted from `evsphereofficial/elevia-skills` ([MIT](https://github.com/evsphereofficial/elevia-skills)):
`github/github-project-publishing.md` v1.0.0. J5 additions: worthiness table
as required artifact, token-scope gotcha, hygiene-before-create ordering.
