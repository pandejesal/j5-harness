---
name: test-plan
description: >-
  Generate a requirement-to-test matrix from a spec delta and code diff.
  Input: spec section + diff_sha. Output: requirement -> test_cmd -> expected -> actual
  matrix. Mandates 1 negative + 1 boundary case per changed contract.
  All test commands must be executable and self-contained.
---

# test-plan

Produces a structured test plan that maps every changed contract to concrete,
executable test commands. Ensures negative and boundary coverage are never skipped.

## Trigger

Use when: generating test plans from spec changes, creating validation matrices,
or invoked via `/test-plan <diff_sha>`.

## Input

| Parameter     | Required | Description |
|---------------|----------|-------------|
| `diff_sha`    | yes      | Full 40-char SHA of the commit/PR head |
| `spec_path`   | no       | Path to the relevant spec section |
| `base_sha`    | no       | Merge-base SHA; defaults to `HEAD~1` |

## Output format

### Requirement -> Test matrix

Every changed contract must appear in the matrix:

```
## requirement: <FR-NNN or contract description>
- test_cmd: <exact shell command to run>
- expected: <pass/fail + expected output pattern>
- actual: <to be filled after execution>
- case_type: positive | negative | boundary
- diff_ref: <file:line of the contract change>
```

### Coverage mandates

For **every changed contract** (function signature, API endpoint, config schema,
data format, etc.), the plan MUST include:

1. **At least 1 positive case** -- happy path with valid inputs
2. **At least 1 negative case** -- invalid input, error condition, or rejection
3. **At least 1 boundary case** -- edge value (empty, zero, max-length, null,
   boundary of valid range)

If a contract cannot reasonably have a negative or boundary case, the plan must
explicitly state why with a justification line:

```
- negative_case: SKIPPED -- <reason>
- boundary_case: SKIPPED -- <reason>
```

### Summary block

End with:

```
## summary
contracts_changed: <N>
total_tests: <M>
positive: <P> | negative: <N> | boundary: <B>
coverage_gaps: <list of any gaps, or "none">
```

## Workflow

1. Receive `diff_sha`. Run `git diff <base_sha>...<diff_sha> --stat` to identify
   changed files.
2. Extract changed contracts: function signatures, exported types, API routes,
   config keys, data schemas.
3. For each contract, check the spec (if `spec_path` provided or detectable from
   project convention) for the requirement it satisfies.
4. Generate the three mandatory test cases per contract.
5. Emit the matrix in the format above.
6. Run the summary block.

## Anti-patterns

- **Missing negative/boundary**: Matrix with only positive cases is rejected.
- **Untestable commands**: `test_cmd` must be a concrete, executable command --
  not a description like "test that errors are handled".
- **Vague expected output**: Must include specific pass/fail criteria or output
  pattern match, not "should work".
