---
name: stata-run
description: Run arbitrary Stata code or a .do file and display the result.
---

The argument is the Stata code or absolute path to a `.do` file to execute.

1. If the argument ends in `.do` or `.ado`, call:
   ```
   stata run --file <argument>
   ```
   Otherwise call:
   ```
   stata run --echo "<argument>"
   ```

2. If the command completes successfully (`rc=0`), display the stdout output. Note the output may be truncated; if a log path is shown, offer to tail the full log with `stata log tail`.

3. If the command fails (`rc != 0`):
   - Run `stata log errors` first (< 5 ms).
   - Display the error message and `rc` code.
   - Only if ambiguous, use `stata log tail --lines 100`.
   - Never read the full log file.
   - Suggest using `stata lint <path>` for syntax issues or `stata help <command>` for documentation.

4. If the command produces graphs, note that `stata graph list` can show them and `stata graph export` can save them.

**If using background mode** (`--background`): you may do other work or fire parallel tasks, but you MUST call `stata task status --task-id <id> --wait` with an appropriate timeout for every task before returning to the user. Loop on timeout until status is `completed` or `failed`.

## CLI Reference

| Command | Description |
|---|---|
| `stata run [--echo] [--session NAME] "<code>"` | Run Stata code |
| `stata run --file /path/file.do [--session NAME]` | Run a do-file |
| `stata run --background --echo "<code>"` | Run in background |
| `stata run --strict --echo "<code>"` | Skip error wrapper (use for do-files) |
| `stata task status --task-id ID --wait` | Wait for background task to finish |

- State persists across commands in the same session.
- Default session is `"default"`. Use `--session NAME` for isolated workspaces.
- Graphs are auto-detected after each run. Use `stata graph list` to see them.
