---
name: stata-environment-diagnose
description: Diagnose local Stata, package, startup, graph-export, and permissions issues. Use when setup is failing, Stata is not discovered, packages are missing, logs are truncated, or a managed machine behaves differently from a normal workstation.
---

# Environment Diagnose

Use this skill for setup and platform troubleshooting.

1. Run `stata doctor` for a full environment report (Python version, Stata discovery, pystata-x availability, daemon health).
2. Run `stata discover` to check Stata discovery independently.
3. Reproduce the smallest failing command with `stata run --echo "<minimal_code>"`.
4. Check `stata log errors` for structured error extraction.
5. Use `stata daemon status` to verify daemon health.
6. Separate root cause, evidence, remediation, and verification.

## Common Checks

| Check | Command |
|---|---|
| Stata binary location | `stata doctor` or `stata discover` |
| Daemon state | `stata daemon status` |
| Package availability | `stata run "which reghdfe; which gtools"` |
| Graph export readiness | `stata run "sysuse auto, clear; scatter price mpg; graph export test.png, replace"` |
| Log output | Check `~/.cache/stata-agent/logs/` |

Read `references/troubleshooting.md` for the diagnosis flow and use `stata doctor --json` for a deterministic environment summary.
