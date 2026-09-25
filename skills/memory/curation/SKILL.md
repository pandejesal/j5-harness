---
name: memory/curation
description: >-
  Memory lifecycle: hot/cold tiers, typed stores, derive-curate-verify loop,
  write-constrained maintenance. Input: session episodes. Output: curated
  durable knowledge with audit trail.
---

# memory/curation

Memories rot, duplicate, and contradict unless curated. This skill defines the
lifecycle every memory passes through, and the maintenance discipline that
keeps the store trustworthy.

## Trigger

Use when: consolidating session outcomes, deduplicating knowledge, archiving
stale entries, verifying store integrity, or an agent's recall quality drops.

## 1. Typed stores (never one big bucket)

| Store | Holds | Example |
|---|---|---|
| `memories` (+`memory_type`) | Durable facts, hot or cold tier | project conventions |
| `behaviour` | Observed user/agent patterns | "user gets frustrated when code fails" |
| `preferences` | Stated likes, stack choices | "prefers python" |
| `rules` | Hard constraints | "never force delete" |
| `agent_written_memory` | Agent's own notes | "refactored xyz" |
| `users` | Who the user is | name, location, context |

**Hot vs cold:** `hot_memory` = active, recall-first; `cold_memory` =
archived but searchable. Promotion is earned (reused + confirmed);
demotion is scheduled (unused + old). Importance is a number (0–1),
updated in place with a reason — never silently.

## 2. The derive → curate → verify loop

1. **Derive** — new episodes (messages, diffs, outcomes) are processed once,
   in order, behind a cursor (`last_processed_rowid` pattern: crash-safe,
   resumable, never double-processed).
2. **Curate** — each derived item gets one disposition: **promote** (durable
   + indexed), **update** (merge into existing, keep reason), **archive**
   (cold tier, still searchable), **quarantine** (contradicted, held for
   review), **delete** (wrong/secret — with audit entry).
3. **Verify** — after any maintenance: index coherence (every durable row
   indexed, every index row live), counts sane, cursor advanced.

J5 mapping: `knowledge_recall` → `curator_analyze` →
`knowledge_add`/`knowledge_archive` + `knowledge_receipt` (the receipt IS the
audit trail). Session harvesting via `MEMORY-MIRROR.md` + shelve/resume.

## 3. Recall discipline (context requests)

Recall with parameters, not vibes: `top_k` (default 5), max semantic
distance cutoff, and **prefer most-derived** — consolidated knowledge
outranks raw episodes. Observer/observed scoping (agent vs user) keeps
perspectives separate.

## 4. Write-constrained maintenance (the important discipline)

Any script that touches the store MUST:

- Declare its write set up front (tables it may write); everything else is
  read-only, with **pre/post counts asserted equal** — violation rolls back.
- Sanity-check schema before running (expected tables/indexes present, or
  refuse — never migrate implicitly).
- Run in ONE transaction: collect → modify → verify → commit; any failure
  rolls back to zero partial writes.
- Print a summary: rows touched, index rows reconciled, cursor new value,
  read-only tables confirmed unchanged.

## 5. Reputation (per-agent memory)

Track per agent/entity: dispatches, successes, failures, corrections,
**doom-loops** (repeated failure cycles), tokens consumed, semantic scores.
Route toward high-reputation agents; quarantine chronic doom-loopers. J5's
router EMA is the live version of this table — feed it outcomes, not hopes.

## Verify before use

- [ ] Every derived item has exactly one disposition (none lost, none double).
- [ ] Cursor advanced past processed rows (re-runs resume, never repeat).
- [ ] Index coherent after maintenance (row counts reconcile).
- [ ] Write-set declaration present on every maintenance script.

## Source

Adapted from `evsphereofficial/evsmem` (owner's repo; patterns from
`models.py` workspace/session/peer/message/memory/reputation schemas,
`.cleanup/cleanup_memories.py` write-constrained hygiene,
`tests/test_curation.py` lifecycle rules) and
`evsphereofficial/elevia-skills` conventions. Commit references on file.
J5 mapping: Mnemosyne SQLite + `tools/memory/mnemosyne-mirror.ps1` +
knowledge receipt ledger.
