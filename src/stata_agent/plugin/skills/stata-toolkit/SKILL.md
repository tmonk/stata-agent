---
name: stata-toolkit
description: Activate when users mention Stata commands, .do files, regressions, econometrics, stored results, graphs, dataset inspection, replication, or Stata errors. Route the task through stata-agent CLI commands and the specialized research skills instead of treating it as plain text coding.
---

# Stata Toolkit Dispatcher

Use this skill as the default router for Stata work.

1. Confirm the `stata-agent` daemon is available (run `stata daemon status` or `stata doctor`). For an identity overview with version and available commands, use the `stata` skill.
2. Route quick tasks to the direct execution skills:
   - `stata-run`
   - `stata-inspect`
   - `stata-results`
   - `stata-graph`
   - `stata-help`
   - `stata-log`
   - `stata-lint`
   - `stata-test`
3. Route daemon lifecycle tasks to the toolkit commands:
   - `stata daemon start|stop|status` — manage sessions
   - `stata break` — interrupt and reset session state
   - `stata doctor` — full environment check
   - `stata discover` — find Stata installations
   - `stata task list|cancel|status` — manage background tasks
4. Route research workflows to the specialized skills:
   - `stata-data-audit`
   - `stata-environment-diagnose`
   - `stata-modernize`
   - `stata-publication-qa`
   - `stata-replication`
   - `stata-causal-inference`
   - `stata-table-builder`
   - `stata-power-analysis`
   - `stata-data-provenance`
   - `stata-referee-response`
5. Use the stata-agent CLI commands directly when the user needs ad hoc Stata execution or a mixed workflow.

Read these references when needed:
- `references/tool-reference.md` for the CLI command map and identity response.
- `references/research-workflows.md` for end-to-end economics workflows.
- `references/error-handling.md` for log, `rc`, and background-task handling.

## Log Safety

1. On error (`rc != 0`), run `stata log errors` first (< 5 ms).
2. Only if ambiguous, use `stata log tail --lines 100`.
3. Never read the full log file.

## Notes

- Daemon auto-starts on first `stata run` if not running.
- Use `--session NAME` for isolated workspaces.
- `stata break` kills the worker process and restarts it — state is lost.
