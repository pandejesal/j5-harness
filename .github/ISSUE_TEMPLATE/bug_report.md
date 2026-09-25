---
name: Bug report
about: Something in J5 broke or misbehaved. Thank you for testing the beta!
title: "[bug] "
labels: bug
assignees: ""
---

## What happened
<!-- One or two sentences: what did you run, what went wrong. -->

## Command
<!-- Exact command, e.g. `j5 run --project wsb-alpha --prompt "..."` (redact secrets!) -->

## Expected
<!-- What should have happened. -->

## Actual
<!-- What happened instead. Paste the LAST 30 lines of output, redacted. -->

## Environment
- OS: [e.g. Windows 11 / Ubuntu 22.04 / WSL2]
- Python: [output of `python --version`]
- J5 version/commit: [output of `j5 --version`, or commit SHA]
- Gateway: [auto / cli / http — from the `Gateway:` line, if shown]

## Checklist
- [ ] I redacted tokens, keys, and private paths from the output above
- [ ] I checked existing issues for duplicates
- [ ] I can reproduce this (or it happened once — say which)
