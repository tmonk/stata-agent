# Error Handling

- Surface `rc` codes explicitly when Stata returns an error.
- If output is truncated, read the full log with `stata log tail`.
- Use `stata lint <path>` for do-file syntax issues before debugging.
- Use `--background` plus `stata task status --task-id <id> --wait` for long-running jobs.
- Use `stata break` to interrupt a running command in-session.
- Use `stata task cancel --task-id <id>` for background-task cancellation.
- Always run `stata log errors` first on failure (< 5 ms) — only if ambiguous use `stata log tail --lines 100`. Never read the full log.
