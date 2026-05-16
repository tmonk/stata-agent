---
name: stata-inspect
description: Describe and summarize the current dataset in memory. Optionally inspect a specific variable with codebook.
---

If an argument (variable name) is provided:
1. Call `stata inspect codebook <variable>` and display the codebook output.

If no argument is provided:
1. Call `stata inspect describe` — display the dataset structure (obs, vars, types, labels).
2. Call `stata inspect summary` — display descriptive statistics (N, mean, sd, min, max).
3. Present both results in a clear, readable format.

If either call returns an error indicating no data in memory, tell the user to load data first (e.g., `stata run "sysuse auto, clear"`).

## CLI Reference

| Command | Description |
|---|---|
| `stata inspect describe [varlist] [--fullnames]` | Dataset structure (obs, vars, types, labels) |
| `stata inspect summary [varlist]` | Descriptive statistics (N, mean, sd, min, max) |
| `stata inspect codebook [varlist]` | Variable codebook information |
| `stata inspect list [varlist] [--from N] [--count M]` | List data values |
| `stata inspect get --format csv\|json --out /path` | Export dataset to file |

- All commands require a loaded dataset.
- `inspect get` exports the current dataset to CSV or JSON.
