# Causal Designs

Use this checklist:

- DiD and event study: pre-trends, treatment timing, cohort composition
- IV: first stage strength, exclusion concerns, interpretation of LATE
- RD: bandwidth, polynomial sensitivity, manipulation checks
- Matching and weighting: overlap, balance, trimming, estimand clarity

Report both what the estimate says and how credible the identifying assumptions look.

Use `stata results --return e` to retrieve estimation results and `stata inspect describe` / `stata inspect summary` to examine the dataset before running models.
