# Troubleshooting Flow

Start with:

1. `stata doctor` — full environment report
2. `stata discover` — check Stata binary discovery
3. the smallest failing `stata run --echo "<code>"`
4. `stata log errors` and `stata log tail` if output is truncated

Common buckets:

- `STATA_PATH` missing or wrong
- missing user-written packages such as `reghdfe` or `gtools`
- startup/profile side effects
- permissions problems affecting temp files, logs, or graphs
- workstation differences across lab or coauthor machines

Use `stata doctor --json` for a deterministic environment summary before recommending a fix.
