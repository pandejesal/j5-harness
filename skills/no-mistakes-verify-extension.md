---
name: no-mistakes-verify-extension
description: Extension adding VERIFY step to no-mistakes skill — diff-evidence + foreign-agent rerun; self-rerun invalid
version: 1.0.0
author: Harness Optimization
license: MIT
---

# no-mistakes VERIFY Extension

## VERIFY Step (inserted between TEST and DOCUMENT)

When the test step completes (regardless of pass/fail), the VERIFY step runs before documentation:

### 1. Diff Evidence Collection
- Capture `git diff --stat` + `git diff` for the working tree
- Hash the diff: `diff_sha = sha256(git diff)`
- Record: files changed, lines added/removed, key function signatures modified

### 2. Foreign-Agent Rerun
- **Rule**: The implementer MUST NOT rerun their own tests
- Spawn a fresh verification agent (different agent-id) to:
  - Checkout the same commit
  - Run the exact same test command (`test_cmd` from receipt)
  - Capture exit code and output
- Compare: verifier exit code MUST match implementer exit code
- If mismatch → VERDICT: FAIL, block DONE

### 3. Self-Rerun Invalid
- Any verification where `verifier_id == implementer_id` is INVALID
- Must be rejected at receipt schema validation
- Auto-fail DONE transition with evidence: "self-rerun detected"

### 4. Evidence Bundle
Attach to receipt:
```
diff_sha: <sha256>
implementer_id: <agent-id>
verifier_id: <different-agent-id>
test_cmd: <exact command>
test_exit: <code>
findings: [{file_line, description, severity, check_id}]
```

### Integration with no-mistakes
This step runs in the no-mistakes pipeline between TEST and DOCUMENT:

```
intent → rebase → review → test → VERIFY → document → lint → push → PR → CI
```

**VERIFY gate failure blocks**: document, lint, push, PR, CI — full stop until foreign verification passes.