---
name: stata-referee-response
description: Organize and execute Stata workflows for referee responses, robustness requests, and coauthor follow-ups. Use when the user needs to answer a critique with targeted reruns, tables, figures, and a defensible audit trail.
---

# Referee Response

Use this skill when the task is to answer a critique rather than merely rerun code.

1. Translate the critique into a finite set of empirical checks.
2. Keep outputs tied to the exact request.
3. Separate confirmed findings, changed results, and unresolved issues.

Use `stata run` for each requested specification, `stata results` to capture point estimates and standard errors, `stata graph export` to produce figures for the response, and `stata log tail` to capture the audit trail.

Read `references/response-patterns.md` for the workflow template.
