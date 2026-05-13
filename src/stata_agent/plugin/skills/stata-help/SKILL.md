# stata-help

Get Stata help documentation (stateless subprocess, no daemon needed).

## Commands

- `stata help <topic>` — Full help text
- `stata help <topic> --format syntax` — Syntax only
- `stata help <topic> --format options` — Options only
- `stata help <topic> --format examples` — Examples only
- `stata help <topic> --format summary` — Syntax + stored results
- `stata help <topic> --max-lines N` — Limit output length

## Notes

- Runs `stata-se -q` as subprocess (not through daemon).
- Terminal escape sequences are stripped automatically.
- Batch mode (`-b`) blocks help; quiet interactive (`-q`) is required.
