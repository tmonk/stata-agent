# stata-toolkit

Root skill for Stata operations. Manages daemon lifecycle and utility commands.

## Commands

- `stata daemon start [--session NAME] [--mock]` — Start daemon for persistent session
- `stata daemon stop [--session NAME]` — Stop daemon
- `stata break [--session NAME]` — Interrupt running command (resets session state)
- `stata doctor` — Check environment (Python, Stata, pystata, daemon)
- `stata discover` — Find Stata installations
- `stata task list [--session NAME]` — Show background tasks
- `stata task cancel --task-id ID` — Cancel a background task

## Log Safety

1. Run `stata log errors` first on failure.
2. Only if ambiguous, use `stata log tail --lines 100`.
3. Never read the full log file.

## Notes

- Daemon auto-starts on first `stata run` if not running.
- Use `--session NAME` for isolated workspaces.
- `stata break` kills the worker process and restarts it — state is lost.
