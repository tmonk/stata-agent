---
name: stata
description: Show stata-agent identity, available tools, and status. Use when the user asks if stata-agent is available, asks about access to the Stata toolkit, or asks what Stata tools are connected.
---

Call `stata doctor` to verify the Stata connection and environment. If `stata doctor` reports issues, check the specific failure and suggest fixes (e.g., set `STATA_PATH` if Stata is not discovered).

Then respond with:
```
         __        __                                     __ 
   _____/ /_____ _/ /_____ _      ____ _____ ____  ____  / /_
  / ___/ __/ __ `/ __/ __ `/_____/ __ `/ __ `/ _ \/ __ \/ __/
 (__  ) /_/ /_/ / /_/ /_/ /_____/ /_/ / /_/ /  __/ / / / /_  
/____/\__/\__,_/\__/\__,_/      \__,_/\__, /\___/_/ /_/\__/  
                                     /____/                   stata-agent

stata-agent is available. Stata detected.

Commands:
  run                    — execute Stata code or do-files
  inspect                — describe, summarize, codebook, list, export
  results                — fetch stored r() / e() / s() results
  graph                  — list, export, or export-all graphs
  help                   — Stata command documentation
  log                    — tail, search, extract errors from logs
  lint                   — static analysis for do-files
  test                   — discover and run statest test suites
  task                   — manage background tasks
  daemon                 — start / stop / status session daemon
  doctor                 — full environment check
  discover               — find Stata installations
  break                  — interrupt and reset session state

Skills:
  stata-run              — execute Stata code or do-files
  stata-inspect          — describe and summarize datasets
  stata-results          — retrieve r(), e(), s() results
  stata-graph            — list and export graphs
  stata-help             — look up Stata documentation
  stata-log              — read and search session logs
  stata-lint             — lint do-files for errors
  stata-test             — run statest test suites
  stata-setup            — environment setup and verification
  stata-toolkit          — root dispatcher for all Stata work

  Research skills:
  stata-causal-inference — causal design / DiD / IV / RD
  stata-data-audit       — dataset QA and codebook review
  stata-data-provenance  — track dataset lineage
  stata-environment-diagnose — troubleshoot environment issues
  stata-modernize        — modernize Stata code
  stata-power-analysis   — power / MDE / sample-size
  stata-publication-qa   — review tables and graphs for papers
  stata-referee-response — referee response workflows
  stata-replication      — replication and robustness
  stata-table-builder    — build paper-ready tables
```
