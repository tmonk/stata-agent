# stata-run

Execute Stata commands in persistent sessions.

## Commands

- `stata run [--echo] [--session NAME] "command"` — Run Stata code
- `stata run --file /path/file.do [--session NAME]` — Run a do-file
- `stata run --background --echo "long command"` — Run in background
- `stata run --strict --echo "command"` — Skip error wrapper (use for do-files)
- `stata task status --task-id ID --wait` — Wait for background task

## Log Safety

1. On error (`rc != 0`), run `stata log errors` first (< 5 ms).
2. Only if ambiguous, use `stata log tail --lines 100`.
3. Never read the full log file.

## Notes

- State persists across commands in the same session.
- Default session is `"default"`. Use `--session NAME` for isolation.
- Graphs are auto-detected after each run. Use `stata graph list` to see them.
