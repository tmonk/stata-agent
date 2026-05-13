# stata-inspect

Inspect Stata datasets and export data.

## Commands

- `stata inspect describe [varlist] [--fullnames]` — Describe variables
- `stata inspect summary [varlist]` — Summary statistics
- `stata inspect codebook [varlist]` — Codebook information
- `stata inspect list [varlist] [--from N] [--count M]` — List data values
- `stata inspect get --format csv|json --out /path` — Export data to file

## Notes

- All commands require a loaded dataset (run `stata run "sysuse auto"` first).
- `inspect get` exports the current dataset to CSV or JSON.
