---
name: stata-table-builder
description: Build and review paper-ready regression, balance, and summary tables from Stata outputs. Use when the user needs a clean table for a draft, appendix, or coauthor share-out.
---

# Table Builder

Use this skill when the target output is a table rather than raw console output.

1. Determine the table type (regression, balance, summary statistics) and target audience.
2. Extract authoritative stored results with `stata results --return e` and `stata results --return r`.
3. Use `stata run` to produce additional tables via commands like `esttab`, `tabout`, or `table`.
4. Check labels, notes, sample definitions, and comparability across columns.

Read `references/table-patterns.md` for table readiness checks.
