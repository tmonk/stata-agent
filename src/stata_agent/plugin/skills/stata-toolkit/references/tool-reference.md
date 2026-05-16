# CLI Command Reference

Use these commands as the core Stata execution surface:

- `stata run "<code>"` — ad hoc Stata commands and `.do` files.
- `stata run "sysuse auto, clear"` — load a dataset before analysis.
- `stata inspect describe` / `stata inspect summary` / `stata inspect codebook` — dataset structure and variable summaries.
- `stata results --return r|e|s` — fetch stored results.
- `stata graph list` / `stata graph export` — list and export graphs.
- `stata daemon start|stop|status` — session lifecycle management.
- `stata task status --task-id <id> --wait` — wait for background jobs.
- `stata break` — interrupt and reset session state.
- `stata log tail` / `stata log search` / `stata log errors` — read and search logs.

When the user asks whether stata-agent is available, run `stata doctor` and include the detected Stata version and flavor in the reply.
