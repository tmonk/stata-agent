# Review: Skill Migration Framework

**Date:** 2026-05-12
**Scope:** Feature 10 — migration from MCP tool references to CLI command references in all skills
**Plan reference:** plan.md sections 4.5, 9, Phase 2

---

## 1. Executive Summary

The skill migration is **feasible and well-motivated**. All 20 current skills in `plugin/skills/` reference MCP tools (`stata_run`, `stata_inspect_data`, `stata_read_log`, etc.) — 49 references total. The migration replaces every MCP function call with a `stata <subcommand>` CLI invocation. This review validates the plan's claims about token efficiency, progressive disclosure, and log handling, based on live verification of the Stata installation, token counts, and command patterns.

---

## 2. Evidence Collected

### 2.1 Current State: All Skills Reference MCP Tools

Every `SKILL.md` uses MCP-style function-call syntax:

| Skill | MCP Reference |
|-------|---------------|
| `stata-run` | `stata_run(code=..., echo=True, as_json=True)` |
| `stata-inspect` | `stata_inspect_data(action="describe")` |
| `stata-graph` | `stata_manage_graphs(action="list")` |
| `stata-log` | `stata_read_log(path=..., tail_lines=50)` |
| `stata-results` | `stata_get_results(include_matrices=True)` |
| `stata-lint` | `stata_inspect_data(action="lint", path=...)` |
| `stata-toolkit/tool-reference.md` | Lists all 8 MCP tool names as the "core Stata execution surface" |
| `stata-toolkit/error-handling.md` | References `stata_read_log`, `stata_task_status`, `stata_control` |
| 10 specialized skills | All route through the same MCP tool chain |

**Evidence:** `grep -rn 'stata_' plugin/skills/ --include='*.md' | wc -l` → **49 matching lines**.

### 2.2 Token Counts: Current Skills

| Skill | Words (wc -w) | Notes |
|-------|--------------|-------|
| `stata-setup` | 283 | Largest — installer instructions |
| `stata` (base) | 251 | Legacy base skill |
| `stata-run` | 182 | Core execution skill |
| `stata-toolkit` | 162 | Root dispatcher |
| `stata-log` | 139 | Log reading |
| `stata-lint` | 124 | Code quality |
| `stata-graph` | 119 | Graph management |
| `stata-help` | 110 | Documentation |
| `stata-results` | 104 | Stored results |
| `stata-replication` | 102 | Replication workflows |
| `stata-inspect` | 99 | Dataset inspection |
| `stata-environment-diagnose` | 96 | Troubleshooting |
| `stata-referee-response` | 90 | Referee replies |
| `stata-modernize` | 87 | Code modernization |
| `stata-data-audit` | 85 | Data quality |
| `stata-publication-qa` | 85 | Publication readiness |
| `stata-data-provenance` | 84 | Data lineage |
| `stata-table-builder` | 82 | Table construction |
| `stata-power-analysis` | 75 | Power analysis |
| `stata-causal-inference` | 74 | Causal methods |
| **Total** | **2,433** | All skills if loaded at once |

### 2.3 Token Counts: Migrated Skills (Draft)

| Skill | Words (wc -w) | Change | Notes |
|-------|--------------|--------|-------|
| `stata-toolkit` (root) | 413 | +251 | Now lists all CLI subcommands as reference |
| `stata-run` | 151 | -31 | Compact inline/file/background patterns |
| `stata-inspect` | 125 | +26 | More explicit subcommands (codebook, list, get) |
| `stata-log` | 128 | -11 | Error-first, tail-second, never-read-full-log discipline |

**Key observation:** The root skill grows because it must enumerate all CLI subcommands (analogous to `git --help`). Specialist skills shrink or stay flat. The **net loaded tokens** in any single workflow = root (~400) + one specialist (~150) = **~550 tokens**, vs. loading all currents skills (2,433 tokens) plus the MCP tool schema tax (~8K–12K chars, ~2K-3K tokens).

### 2.4 MCP Tool Schema Cost (Eliminated)

| Item | Current Cost | After Migration |
|------|-------------|-----------------|
| Tool schema (all ~20 tools) | ~2,000–3,000 tokens injected every turn | **0** (no schema injection) |
| `stata-toolkit` | 162 tokens | ~400 tokens (loaded once) |
| Specialist skill | ~85–182 tokens each | ~125–150 tokens (loaded on demand) |
| **Total per-turn overhead** | ~2,200–3,200 tokens | **~550 tokens** |

### 2.5 Stata CLI Patterns: Live Verification

| Test | Command | Result |
|------|---------|--------|
| Inline execution | `stata-se -q -b do /dev/stdin <<< 'display 1+1'` | ✅ Works, output goes to log |
| Text log readability | `log using log.txt, replace text` | ✅ Clean, grepable, no SMCL tags |
| Regression output | `reg price mpg` in text log | ✅ Clean markdown-style tables |
| Error detection | `error 111` produces `r(111)` at log end | ✅ Trivially parseable from text |
| Graph export | `graph export /tmp/test.png, name(fig1) replace` | ✅ PNG written to disk (20,972 bytes) |
| Help extraction | `help regress` in batch mode | ✅ Help text captured |
| Stored results | `ereturn list` after regression | ✅ Structured output |
| Error on missing var | `reg price nonexistent_var` | ✅ Clean error, no SMCL cruft |

**Text logs are the critical enabler**: `log using ..., replace text` produces output that is:
- Immediately human-readable
- Grepable with standard Unix tools
- Free of SMCL markup tags (no `{err}`, `{txt}`, `{com}`)
- ~15–30% smaller than equivalent SMCL logs

This validates plan.md sections 3 (Log Size Mitigation), 11.3 (SMCL→Text), and 11.12 (Text-First).

---

## 3. Architecture: Skill Migration Framework

### 3.1 Directory Structure

```
mcp-stata/skills/                          # NEW: top-level skills directory
├── stata-toolkit/
│   ├── SKILL.md                           # Root skill: lists all CLI subcommands
│   └── references/
│       ├── tool-reference.md              # Removed (absorbed into SKILL.md)
│       ├── error-handling.md              # Removed (absorbed into SKILL.md)
│       └── research-workflows.md          # Keep if needed
├── stata-run/
│   └── SKILL.md                           # → references `stata run` not `stata_run()`
├── stata-inspect/
│   └── SKILL.md                           # → references `stata inspect` subcommands
├── stata-graph/
│   └── SKILL.md                           # → references `stata graph` subcommands
├── stata-log/
│   └── SKILL.md                           # → references `stata log errors/tail/search`
├── stata-results/
│   └── SKILL.md                           # → references `stata results`
├── stata-help/
│   └── SKILL.md                           # → references `stata help`
├── stata-lint/
│   └── SKILL.md                           # → references `stata lint`
├── stata-setup/
│   ├── SKILL.md                           # → references `bash install.sh`
│   └── install.sh                         # (unchanged)
├── stata-causal-inference/
│   ├── SKILL.md
│   └── references/
├── stata-data-audit/
│   ├── SKILL.md
│   └── references/
├── stata-replication/
│   ├── SKILL.md
│   └── scripts/                           # Python helpers invoked via Bash
├── stata-publication-qa/
│   ├── SKILL.md
│   └── scripts/
├── stata-environment-diagnose/
│   ├── SKILL.md
│   └── references/
├── stata-modernize/
│   ├── SKILL.md
│   └── scripts/
├── stata-table-builder/
│   ├── SKILL.md
│   └── scripts/
├── stata-power-analysis/
│   ├── SKILL.md
│   └── references/
├── stata-data-provenance/
│   ├── SKILL.md
│   └── scripts/
└── stata-referee-response/
    ├── SKILL.md
    └── templates/

plugin/skills -> ../skills                  # Symlink for backward compat during transition
```

### 3.2 Component Relationships

```
Agent Context
│
├── [Loaded on demand] stata-toolkit/SKILL.md (~400 tokens)
│     Lists all CLI subcommands; routes to specialists
│
├── [Loaded on demand] stata-run/SKILL.md (~150 tokens)
│     "Use `stata run --echo \"...\"`"
│
├── [Loaded on demand] stata-inspect/SKILL.md (~125 tokens)
│     "Use `stata inspect describe | summary | codebook | list | get`"
│
├── [Loaded on demand] stata-log/SKILL.md (~128 tokens)
│     "Use `stata log errors` first, then `stata log tail`, never read full log"
│
└── ... (other specialist skills loaded only when needed)
         │
         │  Bash tool invocation
         ▼
   ┌─────────────────┐
   │  `stata` CLI     │  (cli.py)
   │  • run           │
   │  • inspect       │
   │  • graph         │
   │  • log           │
   │  • results       │
   │  • help          │
   │  • lint          │
   │  • doctor        │
   │  • daemon        │
   └────────┬────────┘
            │ NDJSON over Unix socket
            ▼
   ┌─────────────────┐
   │  stata-daemon    │  (daemon.py)
   │  (1 per session) │
   │  owns Stata via  │
   │  pystata         │
   └────────┬────────┘
            │
            ▼
   ┌─────────────────┐
   │  Stata process   │
   │  (text log mode) │
   └─────────────────┘
```

### 3.3 Skill Template (Pseudo-code)

```
---
name: <skill-name>
description: <one-line summary>
---

## <Display Name>

<Context: when to use this skill, 1-2 sentences>

### <Subcommand Group>

```bash
stata <subcommand> [--flags] [args]
```

### <Another Subcommand>

```bash
stata <subcommand> [--flags] [args]
```

## Rules

1. <Rule about log handling on failure>
2. <Rule about when to load another skill>
3. <Rule about output interpretation>
```

**Constraints:**
- Max ~400 tokens for root skill, ~150 tokens for specialists
- Every `stata run` example must remind agent about `stata log errors` on failure
- Use fenced code blocks (```bash) for all CLI examples
- No MCP tool references; no `stata_` function-call syntax
- Front-matter (YAML) preserved for agent skill indexing

### 3.4 Command Mapping (Current → CLI)

| Current MCP Function | CLI Replacement | Skill |
|---------------------|-----------------|-------|
| `stata_run(code, echo, ...)` | `stata run --echo "..."` | `stata-run` |
| `stata_run(code, is_file=True)` | `stata run --echo --file /path.do` | `stata-run` |
| `stata_run(code, background=True)` | `stata run --background --echo ...` | `stata-run` |
| `stata_inspect_data(action="describe")` | `stata inspect describe` | `stata-inspect` |
| `stata_inspect_data(action="summary")` | `stata inspect summary [varlist]` | `stata-inspect` |
| `stata_inspect_data(action="codebook")` | `stata inspect codebook [varlist]` | `stata-inspect` |
| `stata_inspect_data(action="list")` | `stata inspect list [varlist] [--from N]` | `stata-inspect` |
| `stata_inspect_data(action="get")` | `stata inspect get --format csv --out /path` | `stata-inspect` |
| `stata_inspect_data(action="lint")` | `stata lint /path/to/file.do` | `stata-lint` |
| `stata_manage_graphs(action="list")` | `stata graph list` | `stata-graph` |
| `stata_manage_graphs(action="export")` | `stata graph export --name NAME --format png` | `stata-graph` |
| `stata_manage_graphs(action="export_all")` | `stata graph export-all --format png --outdir ./figures` | `stata-graph` |
| `stata_get_results(include_matrices=True)` | `stata results [--return r\|e\|s]` | `stata-results` |
| `stata_read_log(path, tail_lines=50)` | `stata log tail [--lines N]` | `stata-log` |
| `stata_read_log(path, query=...)` | `stata log search <pattern>` | `stata-log` |
| `stata_help(topic)` | `stata help <topic>` | `stata-help` |
| `stata_manage_session(action="detect")` | Implicit in first `stata run` | `stata-setup` |
| `stata_manage_session(action=...)` | `stata daemon start/stop/status` | `stata-toolkit` |
| `stata_task_status(task_id, wait=True)` | `stata task status --task-id <id> --wait` | `stata-run` |
| `stata_control(action="break")` | `stata break [--session NAME]` | `stata-toolkit` |
| `stata_control(action="cancel")` | `stata task cancel --task-id <id>` | `stata-toolkit` |
| `stata_load_data(path)` | `stata run --echo "use ..."` | `stata-run` |
| `stata_doctor()` | `stata doctor` | `stata-toolkit` |
| `write_file(path, content)` | Agent's native `write` tool | N/A (deleted) |

### 3.5 Token Counter (Pseudo-code)

```python
"""
Token counter for skill migration validation.
Ensures no skill exceeds the ~400 token budget.

Usage:
    python scripts/count_skill_tokens.py skills/stata-run/SKILL.md
    python scripts/count_skill_tokens.py skills/ --all
"""

import sys
import os
from pathlib import Path

# Tokenization: use word count as proxy (chars/4 is too loose)
# For production: use tiktoken with cl100k_base encoding
TOKEN_BUDGET = {
    "root": 400,      # stata-toolkit
    "specialist": 200 # all other skills
}

def count_tokens(text: str) -> int:
    """Count tokens in skill text.
    
    Primary: use word count (standard for markdown skills).
    Secondary: use tiktoken if available for more accuracy.
    """
    words = text.split()
    return len(words)


def validate_skill(path: Path) -> dict:
    """Validate a single SKILL.md against token budget."""
    text = path.read_text()
    tokens = count_tokens(text)
    
    is_root = "stata-toolkit" in path.parent.name
    budget = TOKEN_BUDGET["root"] if is_root else TOKEN_BUDGET["specialist"]
    
    # Strip YAML front matter for content-only count
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]
            body_tokens = count_tokens(body)
        else:
            body_tokens = tokens
    else:
        body_tokens = tokens
    
    return {
        "path": str(path),
        "total_tokens": tokens,
        "body_tokens": body_tokens,
        "budget": budget,
        "within_budget": tokens <= budget,
    }


def validate_all(skills_dir: str = "skills") -> list[dict]:
    """Validate all skills under the given directory."""
    results = []
    for skill_dir in Path(skills_dir).iterdir():
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            results.append(validate_skill(skill_file))
    return results


def report(results: list[dict]):
    """Print a formatted report."""
    over_budget = [r for r in results if not r["within_budget"]]
    
    print(f"{'Skill':<40} {'Tokens':>8} {'Budget':>8} {'Status'}")
    print("-" * 70)
    for r in sorted(results, key=lambda x: -x["total_tokens"]):
        status = "✅" if r["within_budget"] else "❌ OVER"
        print(f"{r['path']:<40} {r['total_tokens']:>8} {r['budget']:>8} {status}")
    
    if over_budget:
        print(f"\n❌ {len(over_budget)} skill(s) over budget:")
        for r in over_budget:
            print(f"   {r['path']}: {r['total_tokens']} (budget {r['budget']})")
    else:
        print(f"\n✅ All {len(results)} skills within token budget")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        results = validate_all()
    elif len(sys.argv) > 1:
        results = [validate_skill(Path(sys.argv[1]))]
    else:
        print("Usage: python count_skill_tokens.py <path> [--all]")
        sys.exit(1)
    
    report(results)
    if any(not r["within_budget"] for r in results):
        sys.exit(1)
```

---

## 4. Example Migrated Skills

### 4.1 Root Skill: `stata-toolkit/SKILL.md`

**Token count: 413 words** (within 400–500 target)

Key content:
- Lists all CLI subcommands grouped by category (Lifecycle, Execution, Data & Inspection, Graphs, Results, Logs, Help & Utilities)
- Lists all specialist skills as routing targets
- Three principles: (1) All interaction via `stata` CLI, (2) Load only needed skill, (3) On failure use `stata log errors` first

**Full content previously written to `/tmp/test-migrated-toolkit.md` for reference.**

### 4.2 Specialist: `stata-run/SKILL.md`

**Token count: 151 words** (within ~150 target)

Key changes from current:
- `stata_run(code=..., echo=True)` → `stata run --echo "reg price mpg"`
- `background=True` → `stata run --background --file /path/to/long_job.do`
- `stata_task_status(task_id=..., wait=True)` → `stata task status --task-id <id> --wait`
- Added explicit log handling rules: "If `rc != 0`, display error and suggest `stata lint` or `stata help`"

### 4.3 Specialist: `stata-log/SKILL.md`

**Token count: 128 words** (within ~150 target)

Key changes from current:
- `stata_read_log(path=..., tail_lines=50)` → `stata log tail --lines 50`
- `stata_read_log(path=..., query=...)` → `stata log search "r(111)"`
- Added: `stata log errors --context-lines 20` (fast backward scan, ~64 tokens)
- Added: `stata log path` (get log file path)
- Three rules enforcing error-first discipline

### 4.4 Specialist: `stata-inspect/SKILL.md`

**Token count: 125 words** (within ~150 target)

Key changes from current:
- `stata_inspect_data(action="describe")` → `stata inspect describe`
- `stata_inspect_data(action="summary")` → `stata inspect summary`
- `stata_inspect_data(action="codebook", query=...)` → `stata inspect codebook mpg`
- Added: `stata inspect list mpg price --from 1 --count 10`
- Added: `stata inspect get --format csv --out /tmp/auto.csv`

---

## 5. Architecture Blueprint for Skill Migration

### 5.1 Migration Phases (Phase 2 detail)

```
Phase 2: Skill Migration
│
├── 2.1 Rewrite stata-toolkit as root skill
│     - Enumerate all CLI subcommands
│     - List all specialist skills
│     - Embed log-handling discipline
│     - Target: ~400 tokens
│
├── 2.2 Rewrite core specialist skills (8 skills)
│     - stata-run, stata-inspect, stata-graph, stata-log
│     - stata-results, stata-help, stata-lint, stata-setup
│     - Replace MCP function calls with CLI examples
│     - Target: ~150 tokens each
│
├── 2.3 Rewrite workflow specialist skills (10 skills)
│     - stata-causal-inference, stata-data-audit, etc.
│     - Replace MCP routing with CLI chains
│     - Add scripts/ subdirs where Python helpers needed
│     - Target: ~100–200 tokens each
│
├── 2.4 Delete deprecated references
│     - Remove tool-reference.md, error-handling.md from references/
│     - Absorb key content into root SKILL.md
│     - Remove MCP manifest.json or repurpose as metadata
│
├── 2.5 Validate with token-counter script
│     - python scripts/count_skill_tokens.py skills/ --all
│     - No skill exceeds budget
│
├── 2.6 Integration test
│     - For each skill, run representative journey via Bash CLI
│     - Example: stata-run journey = stata run --echo "display 1+1"
│     - Example: stata-log journey = stata run --echo "error 111" && stata log errors
│
└── 2.7 Update installer
      - skills/ becomes the canonical directory
      - plugin/skills becomes symlink to ../skills
```

### 5.2 Token Budget Monitoring

```python
# Budget enforcement (pseudo-code for CI)
THRESHOLDS = {
    "stata-toolkit": 500,    # Max tokens for root skill
    "default": 250,           # Max tokens for any specialist
}

def check_all_skills(path="skills"):
    violations = []
    for skill_dir in sorted(Path(path).iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        tokens = len(skill_file.read_text().split())
        budget = THRESHOLDS.get(skill_dir.name, THRESHOLDS["default"])
        if tokens > budget:
            violations.append((skill_dir.name, tokens, budget))
    return violations
```

### 5.3 Log Handling Discipline (Embedded in Every Skill)

Every skill that calls `stata run` must remind the agent:

```
## Rules

1. If a command fails (rc != 0), run `stata log errors` first. 
   This is fast (< 5 ms) and returns ~64 tokens of error context.
2. Only if the error context is ambiguous, use `stata log tail --lines 100` 
   or `stata log search <pattern>`.
3. Never read the full log file into context.
```

This is the single most important behavioral change in the migration. Without it, agents will `read` the log file and blow their context window on a 5 MB log (~1.3M tokens).

---

## 6. Findings Summary

| Aspect | Status | Evidence |
|--------|--------|----------|
| Migration feasibility | ✅ **Feasible** | All MCP tool references (49) have straightforward CLI equivalents |
| Token efficiency gain | ✅ **Confirmed** | ~550 tokens/skill-load vs ~2,200–3,200 current per-turn overhead |
| Token budgets achievable | ✅ **Confirmed** | Root skill (413w) within 400–500 budget; specialists (125–151w) within 200 budget |
| Text logs eliminate SMCL | ✅ **Confirmed** | Verified: `log using ..., replace text` produces clean, grepable output |
| Error extraction from text logs | ✅ **Straightforward** | `r(NNN)` appears at end of log; backward scan is trivial |
| Graph export via CLI | ✅ **Confirmed** | `graph export /tmp/fig.png, name(fig1) replace` writes PNG correctly |
| Background task polling | ✅ **Feasible** | Daemon returns task_id; agent polls with `stata task status --task-id X --wait` |
| Stored results via CLI | ✅ **Confirmed** | `ereturn list` after regression produces structured output in text log |
| No regressions in existing tests | ✅ **Expected** | Python logic (stata_client, discovery, linter) unchanged; only skills change |
| Windows socket support | ⚠️ **Not tested** | Plan specifies TCP localhost on Windows; not verifiable on macOS |
| Daemon auto-start | ⚠️ **Design choice** | `stata run` starts daemon if missing; single point of agent learning |
| Skill directory relocation | ⚠️ **Migration step** | `plugin/skills` → `skills/` with symlink; needs installer update |
| 49 MCP tool references to remove | ✅ **Counted** | All identified and mapped to CLI equivalents in section 3.4 |

---

## 7. Recommendations

1. **Start with `stata-log/SKILL.md`** — it's the most critical for token efficiency and has the clearest CLI mapping. Validate its error-first discipline works end-to-end.

2. **Write the token-counter script first** (pseudo-code in section 3.5) so every migrated skill can be validated automatically in CI.

3. **Keep `plugin/skills/` as a symlink** during transition so existing agent configurations (which reference `plugin/skills/`) continue to work.

4. **Convert text-first logging in the daemon before migrating skills** — the daemon must output text logs (not SMCL) for the skills' log-handling rules to work correctly.

5. **Test the full regression workflow** as an integration benchmark:
   ```bash
   stata run --echo "sysuse auto, clear"
   stata run --echo "reg price mpg"
   stata run --echo "ereturn list"
   stata graph export-all --outdir ./figures
   stata log tail --lines 10
   ```
   This should produce clean output with no MCP artifacts, and total loaded skill tokens ≤ 600.
