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
