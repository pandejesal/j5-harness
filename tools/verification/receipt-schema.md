# Verification Receipt Schema

A verification receipt is a structured record that proves a code change was
reviewed by a different agent than the one that implemented it.

## Receipt Format (Markdown)

```
## verification-receipt
- implementer_id: <agent-id of the coder who made the change>
- verifier_id: <agent-id of the reviewing agent; MUST differ from implementer_id>
- diff_sha: <full 40-char SHA of the verified diff>
- test_cmd: <exact command used to validate>
- test_exit: <exit code: 0 = pass, nonzero = fail>
- timestamp: <ISO 8601 timestamp>
- findings[]:
  - file:line: <path:line of finding>
    description: <1-line finding description>
    severity: P0 | P1 | P2
    check_id: <checklist identifier, e.g. SEC-01>
- verdict: PASS | FAIL | CONDITIONAL
```

## Receipt Template (JSON)

See `receipt-template.json` for the machine-readable version.

## ABANDON Receipt Format

When an implementation attempt is abandoned (not completed), an ABANDON receipt
is filed instead:

```
## abandon-receipt
- implementer_id: <agent-id who attempted the work>
- diff_sha: <SHA of the abandoned diff, or "none" if no commit was made>
- attempt_evidence: <path to the evidence file showing what was attempted>
- reason: <1-line reason for abandonment>
- critic_approval: <agent-id of the critic who approved the abandon, or "none">
- timestamp: <ISO 8601 timestamp>
```

An ABANDON receipt requires critic approval (the `critic_approval` field) before
the task can be re-attempted. If `critic_approval` is `"none"`, the abandon
is provisional and must be confirmed by a critic.

## Validation Rules

1. `implementer_id` MUST NOT equal `verifier_id` (self-review prohibition).
2. `diff_sha` MUST be a valid 40-character hex string (or `"none"` for ABANDON).
3. `test_exit` MUST be present; omitting it implies a pass, which is forbidden.
4. `findings[]` MUST be present even if empty (empty array `[]` is valid for
   a clean pass).
5. ABANDON receipts MUST include `critic_approval` before the task can be
   re-queued.
