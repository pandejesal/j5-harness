---
name: spec-staleness
description: >-
  Detect spec-to-code drift by comparing a spec document against a code diff.
  Input: spec_path + diff_sha. Output: STALE or OK per section with
  spec-path:line vs code-path:line mapping. STALE verdict blocks DONE.
---

# spec-staleness

Audits whether specification sections are still consistent with the actual code
after a change. A `STALE` verdict on any section **blocks** task completion.

## Trigger

Use when: verifying spec accuracy after implementation, checking documentation
drift, or invoked via `/spec-staleness <diff_sha>`.

## Input

| Parameter     | Required | Description |
|---------------|----------|-------------|
| `diff_sha`    | yes      | Full 40-char SHA of the commit/PR head |
| `spec_path`   | yes      | Path to the spec file to audit |
| `base_sha`    | no       | Merge-base SHA; defaults to `HEAD~1` |

## Output format

### Per-section verdict

For each auditable section of the spec:

```
## section: "<section heading>"
- verdict: STALE | OK
- spec_path:line: <spec file path>:<line number of the claim>
- code_path:line: <code file path>:<line number of the matching implementation>
- delta: <description of what changed or diverged, or "consistent">
- confidence: HIGH | MEDIUM | LOW
```

### STALE definition

A section is **STALE** when:
- The spec describes behavior, parameters, or contracts that no longer match
  the code after the diff.
- The spec omits a new behavior or contract introduced by the diff.
- The spec contradicts the code in a material way (not just wording).

### OK definition

A section is **OK** when:
- The spec accurately describes the current code behavior.
- The section is purely informational (design rationale, background) and is
  not contradicted by the code.

### Confidence levels

| Level  | Meaning |
|--------|---------|
| HIGH   | Automated check confirmed exact match or exact mismatch |
| MEDIUM | Heuristic match; partial overlap between spec and code |
| LOW    | Cannot determine; requires human review |

### Summary block

End with:

```
## summary
sections_audited: <N>
stale: <S> | ok: <K> | uncertain: <U>
verdict: BLOCKED (if S > 0) | PASS (if S == 0)
stale_sections:
  - "<section heading>" -- <reason>
```

## Workflow

1. Read the spec file at `spec_path`.
2. Extract sections with verifiable claims (function behavior, parameter specs,
   output formats, constraints).
3. Run `git diff <base_sha>...<diff_sha>` to obtain the change set.
4. For each spec section, search the diff and surrounding code for the matching
   implementation.
5. Emit per-section verdict with `spec_path:line` and `code_path:line` references.
6. Emit summary. If any section is `STALE`, the overall verdict is `BLOCKED`.

## Blocking behavior

When the summary verdict is `BLOCKED`:
- Task completion (`DONE`) is **not allowed**.
- The agent must fix the spec or the code to resolve staleness before proceeding.
- The `stale_sections` list becomes the remediation backlog.

## Anti-patterns

- **Missing line references**: Verdicts without `spec_path:line` or
  `code_path:line` are invalid.
- **False OK**: Marking a section OK when the diff introduces behavior not
  described in the spec.
- **Skipping sections**: Every verifiable section in the spec must receive a
  verdict.
