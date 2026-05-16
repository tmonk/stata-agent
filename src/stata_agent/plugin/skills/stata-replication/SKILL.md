---
name: stata-replication
description: Run replication, robustness, and specification-sensitivity workflows for Stata projects. Use when a researcher wants to reproduce a result, rerun a pipeline, compare specifications, audit a do-file sequence, or check whether a claim is stable.
---

# Replication And Robustness

Use this skill for reproducibility work rather than one-off execution.

1. Identify the replication entrypoint (the master `.do` file or ordered sequence of do-files).
2. Run the baseline cleanly with `stata run --file <entrypoint>` and capture logs and stored results with `stata log tail` and `stata results`.
3. Use `stata log errors` to check for warnings or deviations.
4. Compare requested variants in a structured way.
5. Say whether the result truly replicates, partly matches, or breaks.

Read `references/workflow.md` for the replication checklist.
