---
name: stata-causal-inference
description: Design, run, and critique causal inference workflows in Stata. Use when the user is working on identification, treatment effects, DiD, IV, event studies, RD, or assumption-sensitive empirical claims.
---

# Causal Inference

Use this skill when the question is causal, not merely predictive.

1. Clarify the identification strategy.
2. Check the right diagnostics and assumptions for the design.
3. Separate point estimates from identification credibility.

Use `stata run` to execute the relevant models (regress, ivregress, didregress, rdrobust, etc.) and `stata results` to retrieve stored e() results. Use `stata inspect describe` and `stata inspect summary` to examine the dataset before estimation.

Read `references/designs.md` for design-specific guidance.
