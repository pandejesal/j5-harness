---
namespace = "coding"
name = "codebase-education"
version = "1.0.0"
capabilities = ["tutor", "onboarding"]
trigger_patterns = ["teach me", "explain codebase", "walk me through", "onboard"]
applicable_agents = ["coding", "general"]
dependencies = {}
contract = { inputs = { task = { type = "str", required = true } }, outputs = { guidance = { type = "str" } } }
self_tests = [{ match = { task = 'smoke' }, not_match = { task = 123 } }]
---
# coding/codebase-education

A lecture is forgotten; a questioned engineer remembers. This skill turns any
codebase into a tutored walkthrough where the USER explains first and the
agent corrects, fills gaps, and goes deeper. Pairs with
`coding/codebase-inspection` (inspect for facts first, then teach).

## Trigger

Use when: "teach me this codebase", onboarding, interview prep on your own
project, learning a stack through a real repo, or finding the edges of your
own understanding.

## The loop (every phase)

1. Agent presents what it found (smallest sufficient slice).
2. Agent asks ONE sharp question ("why X over Y?", "what does this block do?").
3. User answers (or says "don't know" — that's the point, not a failure).
4. Agent confirms/corrects/fills gaps, records the gap.
5. Next question. User may redirect anytime.

In J5, questions go through the `question` tool (bounded options + custom
answer); gaps accumulate into a gap list that becomes follow-up tasks or
`memory/curation` entries.

## Phases

1. **Survey** — structure, LOC split, entry point, key modules. Open with
   your read of each directory's job before any explanation lands.
2. **Architecture** — data flow, component boundaries, pattern choices,
   state, error handling, scaling limits. Always "why this and not that".
3. **Modules** — block-by-block through key files: what each block does,
   in your words first.
4. **Math & algorithms** — triggers on formulas, scoring, model code:
   derive it together, don't recite it.
5. **Security & production** — auth, injection surfaces, secrets, readiness.
   Ends with teach-back: user explains the whole system unprompted.

## Verify before use

- [ ] Inspection facts gathered first (no tutoring from vibes).
- [ ] Every phase ends with recorded gaps, not just good feelings.
- [ ] Teach-back completed — the user can explain it cold.

## Source

Adapted from `evsphereofficial/elevia-skills` ([MIT](https://github.com/evsphereofficial/elevia-skills)):
`github/codebase-education.md` v1.0.0. J5 additions: `question`-tool loop
mechanics, inspection-first prerequisite, gap-to-memory pipeline.
