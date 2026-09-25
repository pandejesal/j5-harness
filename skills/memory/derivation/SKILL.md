---
name: memory/derivation
description: >-
  Turn episodes into durable knowledge: cursor-driven batch derivation,
  noise filtering, tool-call application, reputation, pruning, and
  copy-first migration discipline. Input: unprocessed episodes. Output:
  typed memories + audit trail.
---

# memory/derivation

Derivation is how raw session episodes become knowledge you can trust. The
pipeline below runs on a schedule, processes each episode exactly once, and
proves it did so. Migration moves stores forward without ever risking the
live database.

## Trigger

Use when: harvesting a session into memory, backfilling unprocessed history,
pruning hot memories, assessing agent reputation, or migrating a memory
store to a new schema.

## 1. Cursor-driven batches (exactly-once)

- Pull the oldest unprocessed window (hour batches work well).
- Filter **workflow noise** first (tool-call chatter, status pings, retries)
  — noise stored as knowledge is pollution with a timestamp.
- Mark rows processed ONLY after their results are stored. Crash between
  store and mark = reprocess (idempotent stores make this safe); crash
  between mark and store = lost knowledge (never allow this order).
- Advance an analysis cursor separately from the row cursor so scheduling
  (`seconds_until_next_window`) and progress never conflate.

J5 mapping: `deriver_state.last_processed_rowid` ≡ process ledger lines in
order; `MEMORY-MIRROR.md` harvests are the batch source.

## 2. Analyze with tools, store typed results

Batch → prompt (with existing memory as context) → model returns structured
output + tool calls → **normalize** the response (parsers, not prayers) →
apply calls → store into typed tables (memories, conclusions, user info,
classified items, agent assessments, peer updates). Each store has one writer
function; unknown payload shapes are quarantined, never force-fit.

## 3. Session reputation + pruning (the feedback half)

- Per session: derive reputation (success/failure/corrections/doom-loops)
  and write machine-readable recommendations.
- Prune hot memories on schedule: demote unused + unconfirmed entries to
  cold; deletion requires the write-constrained discipline from
  `memory/curation` (declared write-set, pre/post counts, rollback).

## 4. Migration discipline (copy-first, verify-after)

1. Copy the live DB to temp. NEVER migrate in place.
2. Run migration on the copy.
3. Verify on the copy: expected tables exist, FTS index present, schema
   version advanced, ALL old tables/rows preserved byte-for-byte in count.
4. Report status (current/latest version, needs-migration flag).
5. Only then swap; delete the temp copy after.

## Verify before use

- [ ] Noise filter runs before analysis (spot-check filtered-out rows).
- [ ] Mark-after-store ordering (audit one crash-recovery path).
- [ ] Normalizer rejects malformed model output (no exceptions-as-data).
- [ ] Migration verified on a copy; live DB untouched until swap.

## Source

Adapted from `evsphereofficial/evsmem` (owner's repo): `deriver.py`
pipeline stages (batch/cursor/noise/analyze-with-tools/typed stores/
reputation/prune/scheduler) and `tests/test_migration.py` copy-verify
discipline. Full deriver port (LLM client, embeddings) is a dedicated
project, not this skill — this skill is the operable contract for it.
