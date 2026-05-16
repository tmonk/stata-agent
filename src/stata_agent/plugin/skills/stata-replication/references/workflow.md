# Replication Workflow

1. Identify the authoritative entrypoint.
2. Run the baseline cleanly with `stata run --file <entrypoint>` and save the full log.
3. Capture stored results after each model with `stata results`.
4. Compare requested variants systematically.
5. Distinguish environment failures from substantive result changes.

Do not say a result replicates unless the target output materially matches.

Use `stata log errors` to check for warnings or deviations and `stata log tail` to inspect output.
