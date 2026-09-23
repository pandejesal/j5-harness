# Security Policy

## Supported Versions

Security fixes are provided for the latest `main` branch only. There are no
maintained release branches yet — track `main` and update often.

| Version | Supported          |
| ------- | ------------------ |
| `main` (latest) | :white_check_mark: |
| older commits   | :x:                |

## Reporting a Vulnerability

**Do not open a public issue for security problems.** Instead:

- Email **pandejesal@gmail.com** with subject `[J5-SECURITY]`, including:
  - what is affected (file, command, configuration),
  - steps to reproduce or a proof of concept,
  - what you think the impact is (secret leak, code execution, bypass, …).

You will get a first human reply within a few days. If the report is
confirmed, a fix will be developed privately, then released with credit to
the reporter (unless anonymity is requested).

There is no paid bug-bounty program at this time.

## Scope Notes

J5 intentionally shells out to worker CLIs (`opencode`, `kilo`, …) and runs
a local file bus for agent coordination. When assessing reports, these are
known design properties, not vulnerabilities by themselves:

- worker CLIs execute with the invoking user's privileges by design;
- `tools/state/`, per-project `.harness/` dirs, and the Kilo/InterHarness
  bus hold local operational data — protect them with normal filesystem
  permissions;
- the free-tier model endpoints are third-party services with their own
  rate limits and data handling; J5 never sends them credentials.

## Commercial Licensing

J5 is source-available under the PolyForm Noncommercial License 1.0.0
(see `LICENSE`). Security obligations for commercial deployments are part
of the commercial license terms — contact **pandejesal@gmail.com**.
