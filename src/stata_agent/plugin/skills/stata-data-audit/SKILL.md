---
name: stata-data-audit
description: Audit datasets for structure, missingness, labeling, suspicious values, duplicate identifiers, and documentation readiness. Use when a researcher asks for data QA, codebook review, sanity checks, or pre-analysis cleanup guidance.
---

# Data Audit

Run a compact but explicit audit of the active dataset.

1. Start with `stata inspect describe` and `stata inspect summary`.
2. Use targeted `stata inspect codebook <variable>`, `stata run` checks, and `stata inspect list` for key variables or suspicious patterns.
3. Report concrete issues, not generic reassurance.

Read `references/checklist.md` for the full audit checklist and recommended output format.
