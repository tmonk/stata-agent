# stata-log

Read and search Stata session logs.

## Commands

- `stata log path [--session NAME]` — Show log file path
- `stata log tail [--session NAME] [--lines N]` — Read last N lines
- `stata log search <pattern> [--session NAME]` — Search log for pattern
- `stata log errors [--session NAME] [--context-lines N]` — Extract structured errors

## Error Protocol

1. Always run `stata log errors` first on failure (< 5 ms, ~64 tokens).
2. Only if ambiguous, use `stata log tail --lines 100`.
3. Never read the full log file into context.

## Notes

- Logs are plain text (not SMCL), in `~/.cache/stata-agent/logs/`.
- Backward scan of 6 MB log completes in < 5 ms.
