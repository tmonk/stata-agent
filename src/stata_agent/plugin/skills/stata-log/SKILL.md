---
name: stata-log
description: Tail, read, or search a Stata log file from a previous command or background task.
---

Parse the argument:
- First token: log file path or background task_id
- Second token (optional): search term

**If a search term is provided**, call:
```
stata log search <search_term> --session <session_name>
```
Display matching lines with context.

**If no search term**, call:
```
stata log tail --lines 50
```
Display the last 50 lines of the log.

**If the argument looks like a task_id** (not a file path), call `stata log tail --lines 50` with the appropriate session.

If no argument is provided, tell the user to supply a log file path or task_id. These are returned by `stata run` in the log output.

For structured error extraction, call `stata log errors` first on any failure (< 5 ms, ~64 tokens). Only if ambiguous should you use `stata log tail --lines 100`. Never read the full log file into context.

If the log is large and truncated, note that you can read more with `stata log tail --lines <N>`.

## CLI Reference

| Command | Description |
|---|---|
| `stata log path` | Show log file path for the session |
| `stata log tail [--lines N]` | Read last N lines of the log |
| `stata log search <pattern>` | Search log for a pattern |
| `stata log errors [--context-lines N]` | Extract structured errors |

All commands accept `[--session NAME]` (default: `"default"`).

- Logs are plain text (not SMCL), stored in `~/.cache/stata-agent/logs/`.
- Backward scan of a 6 MB log completes in < 5 ms.
