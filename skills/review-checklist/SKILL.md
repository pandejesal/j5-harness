---
name: review-checklist
description: >-
  Structured code-review checklist that enforces path:line findings with check-ids
  and severity levels. Input: diff_sha. Output: P0/P1/P2 findings, each MUST be
  path:line + 1-line quote + check-id + severity. Bare LGTM is forbidden.
  Verifier identity and diff binding required on every finding line.
---

# review-checklist

Structured code-review skill that produces machine-parseable findings from a diff.
Bare "looks good" or "LGTM" responses are **forbidden** -- every finding must carry
provenance.

## Trigger

Use when: reviewer needs to audit a diff, gate requires checklist findings, or
`/review-checklist <diff_sha>` is invoked.

## Input

| Parameter   | Required | Description |
|-------------|----------|-------------|
| `diff_sha`  | yes      | Full 40-char SHA of the commit/PR head to review |
| `base_sha`  | no       | Merge-base SHA; defaults to `HEAD~1` |
| `scope`     | no       | File glob filter (e.g. `src/**/*.ts`) |

## Output format

Every finding **MUST** match this exact line format:

```
path:line: <excerpt> [check-id/SEV] verifier:<agent-id> diff:<sha>
```

Where:
- `path:line` -- relative file path and 1-indexed line number
- `<excerpt>` -- 1-line quote from the changed code (max 120 chars)
- `check-id` -- identifier from the checklist table below (e.g. `SEC-01`)
- `SEV` -- one of `P0`, `P1`, `P2`
- `agent-id` -- unique identifier of the reviewing agent
- `sha` -- the `diff_sha` being reviewed

### Severity levels

| Level | Meaning | Action |
|-------|---------|--------|
| P0    | Critical / security / data-loss risk | Must block merge; requires fix |
| P1    | Significant quality or correctness issue | Should block merge; requires acknowledgment |
| P2    | Minor / style / nit | Informational; no block |

## Checklist

### Security (SEC)
| ID    | Rule |
|-------|------|
| SEC-01 | No hardcoded secrets, tokens, or credentials |
| SEC-02 | User input validated before use in queries/commands |
| SEC-03 | No unsafe deserialization of untrusted data |
| SEC-04 | File paths sanitized against traversal |

### Correctness (COR)
| ID    | Rule |
|-------|------|
| COR-01 | Error paths handled -- no silently swallowed exceptions |
| COR-02 | Return values checked; no ignored errors |
| COR-03 | Async operations awaited; no fire-and-forget |
| COR-04 | Boundary conditions handled (empty arrays, null, zero) |

### Maintainability (MNT)
| ID    | Rule |
|-------|------|
| MNT-01 | No dead code or unreachable branches |
| MNT-02 | No duplicate logic that should be extracted |
| MNT-03 | Public API surface documented |
| MNT-04 | No magic numbers or hardcoded strings |

### Concurrency (CON)
| ID    | Rule |
|-------|------|
| CON-01 | Shared state access synchronized |
| CON-02 | No TOCTOU race conditions |

## Workflow

1. Receive `diff_sha` from caller.
2. Run `git diff <base_sha>...<diff_sha>` to obtain the change set.
3. For each changed file, walk the diff hunks and apply every applicable
   checklist rule.
4. Emit findings in the required format. **At least 1 finding per changed file**
   is expected -- if a file truly has no issues, emit a `P2` note explaining why
   (e.g. `src/utils.ts:42: pure re-export only [COR-01/P2] verifier:<id> diff:<sha>`).
5. End with a summary line:

```
summary: <N> P0, <M> P1, <K> P2 across <F> files
```

## Anti-patterns

- **Bare LGTM**: Response with zero findings is automatically rejected.
- **Missing provenance**: Finding lines without `verifier:` and `diff:` are invalid.
- **Severity inflation**: Marking style nits as P0 degrades signal; use the
  severity table above.

## Verifier identity

The `verifier:<agent-id>` field MUST be set to the identity of the agent performing
the review. Self-review (where `verifier` matches the `implementer_id` from the
receipt schema) is flagged as a finding itself (`SEC-04/P0`).
