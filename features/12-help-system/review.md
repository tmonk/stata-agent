# Review: Help System Rewrite

**Feature:** 12-help-system  
**Plan ref:** Section 11.9 — Fix Help Extraction  
**Date:** 2026-05-12  
**Status:** Verified with active Stata testing

---

## 1. Executive Summary

The current help system (`get_help()` in `stata_client.py`, ~80 lines + early interception logic in `run_command_streaming` + SMCL→Markdown converter) is convoluted and fragile. The plan proposes replacing it with a simple `help <topic>` invocation captured as text from Stata's stdout, eliminating the `.sthlp` file scraping and the SMCL→Markdown help converter entirely.

**Verdict: The rewrite is feasible, sound, and should be implemented.** Our active verification confirms that `stata-se -q "help <topic>"` produces clean, readable text directly—no SMCL parsing needed.

---

## 2. Active Verification Results

### 2.1 Test Results Summary

| # | Test | Result | Key Finding |
|---|------|--------|-------------|
| 1 | `help regress` via `stata-se -q` | **PASS** | Output is clean text, 20,171 bytes (after stripping terminal control codes). Takes ~28ms wall clock. |
| 2 | `help return` via `stata-se -q` | **PASS** | 7,950 bytes. Dynamic/topical help works identically. |
| 3 | `which regress` and `adopath` | **PASS** | `which regress` returns `/Applications/StataNow/ado/base/r/regress.ado`. `adopath` lists 6 standard paths. |
| 4 | Output size: `help regress` (20,171 B) vs `.sthlp` file (22,763 B) | **PASS** | Help text is **smaller** than raw `.sthlp`—Stata renders help efficiently. |
| 5 | Batch mode (`-b`) blocks help | **BLOCKER** | `stata-se -b` returns "request ignored because of batch mode". Must use `-q` (quiet interactive) mode. |
| 6 | `.sthlp` file locations | **CONFIRMED** | 3,495 `.sthlp` files in `/Applications/StataNow/ado/`, ~27.8 MB total. `sysdir` shows 6 paths. |
| 7 | User-written vs built-in | **PASS** | No user-written packages found on this system. `help` for nonexistent topic returns clean "help for X not found" message. |
| 8 | Token count of `help regress` | **MEASURED** | 2,225 words, 20,171 chars, ~5,042 tokens (chars/4 rule). Fast enough for LLM context. |

### 2.2 Critical Findings

#### Finding 1: `-b` (batch mode) blocks help
```
$ stata-se -b do ...
. help regress
request ignored because of batch mode
```
**Implication:** The help system **must** use `-q` (quiet interactive) mode, not `-b`. This is fine for a stateless help wrapper but means the help command cannot piggyback on the daemon's batch-mode session.

#### Finding 2: Help output bypasses logs
Both SMCL logs and text logs fail to capture `help` output:
- SMCL log file size after `help regress`: 341 bytes (just the log open/close headers, no help text)
- Text log file size after `help regress`: only header + command echo, no help body

**Implication:** Help output MUST be captured from **stdout**, not from log files. The `-q` mode approach is correct.

#### Finding 3: Terminal control characters in `-q` output
```
^[[?1h^[=. help regress
```
Two terminal escape sequences prefix every command:
- `\x1b[?1h\x1b=` — application keypad mode (before command)
- `\x1b[?1l\x1b>` — exit application keypad mode (after output)

These are trivial to strip with a regex or `sed`.

#### Finding 4: Speed
```
$ time stata-se -q "help regress" > /dev/null
real  0m0.028s
user  0m0.139s
sys   0m0.020s
```
28ms wall clock for a comprehensive help topic. The current `.sthlp` file reading approach is slower due to Python file I/O + SMCL parsing overhead.

#### Finding 5: .sthlp files are SMCL-heavy
The raw `.sthlp` file contains:
- `{smcl}` headers
- `{viewerdialog}`, `{vieweralsosee}`, `{viewerjumpto}` navigation tags
- `{p2colset}`, `{p2col:}`, `{p_end}` layout tags
- `{title:}`, `{opt}`, `{bf:}`, `{it:}` formatting tags
- `INCLUDE` directives referencing other files

Stata's built-in help renderer handles all of this. The current `smcl_to_markdown()` function (~400 lines) attempts to replicate this with regex heuristics.

---

## 3. Proposed Architecture

### 3.1 Help Command Wrapper — Pseudocode

```
function help_command(topic: str, max_lines: int = 200, max_chars: int = 16000) -> HelpResult:
    """
    Execute 'help <topic>' in Stata and return cleaned text.
    
    Uses stata-se in -q (quiet interactive) mode, NOT -b (batch) mode,
    because batch mode blocks help output.
    """
    
    # 1. Validate topic (prevent injection)
    sanitized_topic = sanitize_topic(topic)
    if not sanitized_topic:
        return HelpResult(error="Invalid topic", rc=1)
    
    # 2. Build and run command with timeout
    cmd = ['stata-se', '-q', f'help {sanitized_topic}']
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15.0,
        env={'TERM': 'dumb'}  # Suppress terminal control sequences
    )
    
    # 3. Clean output
    raw = proc.stdout
    
    # Strip terminal control characters
    cleaned = re.sub(r'\x1b\[\?1h\x1b=', '', raw)  # Application keypad ON
    cleaned = re.sub(r'\x1b\[\?1l\x1b>', '', cleaned)  # Application keypad OFF
    cleaned = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', cleaned)  # Other ESC sequences
    
    # 4. Detect errors
    if "not found" in cleaned.lower():
        return HelpResult(error=f"Help for '{topic}' not found", rc=111)
    
    # 5. Apply output limits
    lines = cleaned.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"... [truncated at {max_lines} lines]")
    text = '\n'.join(lines)
    if len(text) > max_chars:
        text = text[:max_chars]
        text += f"\n... [truncated at {max_chars} chars]"
    
    return HelpResult(
        topic=sanitized_topic,
        text=text,
        line_count=len(lines),
        char_count=len(text),
        rc=0
    )
```

### 3.2 Output Limiter — Pseudocode

```
function limit_help_output(text: str, strategy: str = "auto") -> LimitedOutput:
    """
    Intelligently limit help text for LLM consumption.
    
    Strategies:
    - "auto":      Return first N lines (syntax + description + options), drop examples
    - "syntax":    Return only the Syntax section
    - "options":   Return only the Options section
    - "examples":  Return only the Examples section
    - "full":      Return full text with line limit
    - "summary":   Return Syntax + Stored results (most token-efficient)
    """
    
    lines = text.splitlines()
    
    if strategy == "full":
        return truncate_lines(lines, max_lines=200)
    
    # Section-based extraction
    sections = extract_sections(lines)
    # Section boundaries detected by: "----" separator lines, 
    # blank-line-delimited headers, "Syntax", "Menu", "Description", etc.
    
    result_lines = []
    
    if strategy in ("auto", "syntax", "summary"):
        result_lines.extend(sections.get("syntax", []))
    
    if strategy == "auto":
        result_lines.extend(sections.get("description", []))
        result_lines.extend(sections.get("options", []))
        if total_length(result_lines) < 8000:
            result_lines.extend(sections.get("examples", []))
    
    if strategy == "options":
        result_lines.extend(sections.get("options", []))
    
    if strategy == "examples":
        result_lines.extend(sections.get("examples", []))
    
    if strategy == "summary":
        result_lines.extend(sections.get("stored results", []))
    
    return LimitedOutput(
        text='\n'.join(result_lines),
        sections_present=list(sections.keys()),
        line_count=len(result_lines)
    )
```

### 3.3 Topic Resolver — Pseudocode

```
function resolve_topic(input_topic: str) -> ResolvedTopic:
    """
    Resolve a help topic to the canonical Stata topic name.
    
    Handles:
    - Exact match (e.g., "regress" → "regress")
    - Prefix match (e.g., "reg" → "regress")
    - Alias resolution (e.g., "lm" → "regress")
    - Command variants (e.g., "logit, or" → "logit")
    - StataNow features (e.g., "hac" → "regress#hac")
    """
    
    # 1. Strip options (everything after comma)
    topic = input_topic.split(',')[0].strip()
    
    # 2. Check for exact match
    result = try_help(topic)
    if result.found:
        return ResolvedTopic(topic=topic, canonical=topic, found=True)
    
    # 3. Check with "which" command for installed commands
    #    which returns the .ado file path or "not found"
    which_result = run_stata(f'capture which {topic}')
    if which_result.success:
        return ResolvedTopic(topic=topic, canonical=topic, found=True)
    
    # 4. Try prefix/suffix matching via adopath
    #    Search .sthlp files in adopath for fuzzy match
    candidates = search_sthlp_files(topic)
    if candidates:
        return ResolvedTopic(
            topic=topic,
            canonical=candidates[0],
            found=True,
            did_you_mean=candidates
        )
    
    # 5. Fall back to "search" command
    search_result = run_stata(f'search {topic}')
    
    return ResolvedTopic(
        topic=topic,
        found=False,
        error=f"Help for '{topic}' not found",
        suggestions=extract_suggestions(search_result)
    )
```

---

## 4. Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        Agent Context                             │
│                                                                  │
│  Agent types: "stata help regress"                               │
│       ↓                                                          │
│  Skill: stata-help/SKILL.md                                      │
│       ↓                                                          │
│  "Run: stata help regress --format summary --max-lines 150"      │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                    stata CLI (cli.py)                             │
│                                                                  │
│  $ stata help <topic> [--format syntax|options|examples|full]    │
│                       [--max-lines N] [--max-chars N]             │
│                       [--plain] [--json]                         │
│                                                                  │
│  Flow:                                                            │
│  1. Parse args, sanitize topic                                   │
│  2. Launch: subprocess.run(["stata-se", "-q", f"help {topic}"]) │
│  3. Strip terminal escape sequences                              │
│  4. Apply output limiter (section-based extraction)              │
│  5. Print result to stdout                                       │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                  Stata Process (stateless)                        │
│                                                                  │
│  $ stata-se -q "help regress"                                    │
│                                                                  │
│  • Uses -q (quiet interactive) mode — NOT -b (batch)             │
│  • Batch mode blocks help with "request ignored"                 │
│  • Help output goes to stdout, NOT to log files                  │
│  • Output includes ~22 bytes of terminal control codes           │
│    that must be stripped                                         │
└──────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Stateless one-shot** | Help is read-only; no session state needed. Each invocation is independent. |
| **`-q` not `-b`** | Verified: `-b` blocks help with "request ignored because of batch mode". |
| **Stdout capture** | Verified: help output bypasses both SMCL and text logs. Must capture from stdout. |
| **Terminal code stripping** | Verified: `\x1b[?1h\x1b=` prefix and `\x1b[?1l\x1b>` suffix are always present in `-q` mode. |
| **Output limiting** | `help regress` is ~20KB/5K tokens. Default limit of 100-150 lines recommended. |
| **Section extraction** | Help text has clear section boundaries (`Syntax`, `Menu`, `Description`, `Options`, `Examples`, `Stored results`). Extract-by-section is more useful than truncation. |
| **No daemon needed** | Help is stateless and fast (~28ms). No reason to route through the session daemon. |

---

## 5. What Gets Removed

| Component | Lines | Reason |
|-----------|-------|--------|
| `get_help()` in `stata_client.py` | ~80 | Replaced by `stata help <topic>` CLI subcommand |
| Early interception in `run_command_streaming()` | ~60 | No longer needed; help is a separate CLI command |
| `_extract_help_topic()` | ~25 | No longer needed |
| `_HELP_TOPIC_RE` / `_HELP_BARE_RE` | ~5 | No longer needed |
| SMCL→Markdown help path in `smcl_to_markdown()` | ~400 | Stata's built-in renderer produces clean text directly |
| `expand_includes()` in `smcl2html.py` | ~30 | No longer needed (Stata handles INCLUDE directives) |
| `_smcl_to_text()` in `stata_client.py` | ~30 | No longer needed |
| **Total removed** | **~630** | Clean, measurable deletion |

### Preserved (unchanged)
- `adopath` / `which` for topic resolution (used only for fallback)
- `stata-se` binary path from `discovery.py` (reused)
- Help skill in `plugin/skills/stata-help/SKILL.md` (rewritten to reference CLI)

---

## 6. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `-q` mode may not be available on all Stata versions | High | Tested on StataNow 19.5. `-q` has been supported since Stata 9. |
| Terminal control codes differ by platform | Medium | Use `TERM=dumb` env var to suppress them at source. Also apply regex strip as fallback. |
| Help output for some topics is very large (>100KB) | Medium | Default `--max-lines 150` cap. CLI warns if output is truncated. |
| Some help topics are dynamically generated (e.g., `help contents`) | Low | Dynamic topics work identically via `help <topic>`; verified with `help return` and `help _variables`. |
| Locating Stata executable | Low | Reuse `discovery.py` from existing codebase. |

---

## 7. CLI Interface

```bash
# Basic usage
stata help regress
stata help return
stata help _variables

# Output limiting
stata help regress --max-lines 100
stata help regress --max-chars 8000

# Section extraction
stata help regress --format syntax        # Syntax only
stata help regress --format options       # Options only
stata help regress --format examples      # Examples only
stata help regress --format summary       # Syntax + stored results

# Structured output
stata help regress --json                 # JSON envelope for programmatic use

# Noise suppression (default with TERM=dumb)
stata help regress --plain                # Strip formatting, plain text only
```

### Exit codes
| Code | Meaning |
|------|---------|
| 0 | Success, help text printed |
| 1 | Help topic not found |
| 2 | Stata executable not found |
| 3 | Timeout (help took >15s) |
| 4 | Invalid topic (sanitization failed) |

---

## 8. Skill Integration

The `stata-help` skill should be rewritten to:

```markdown
---
name: stata-help
description: Look up Stata command documentation and display formatted help text.
---

## Stata Help

Look up documentation for any Stata command or topic.

### Basic help
```bash
stata help <topic>
```

### Focused sections (more token-efficient)
```bash
stata help <topic> --format syntax
stata help <topic> --format options
stata help <topic> --format examples
```

### Compact summary
```bash
stata help <topic> --format summary --max-lines 80
```

### What to do
1. Start with `stata help <topic> --format syntax` to see the command syntax.
2. If you need detailed options, use `stata help <topic> --format options`.
3. If examples are needed, use `stata help <topic> --format examples`.
4. Full help can exceed 5,000 tokens; prefer section extraction.
```

---

## 9. Migration Checklist

- [ ] **Create** `cli/help.py` — help subcommand implementation
- [ ] **Create** `cli/help_limiter.py` — section extraction + output limiting
- [ ] **Create** `cli/help_resolver.py` — topic resolution (exact, fuzzy, alias)
- [ ] **Add** `stata help` subcommand to `cli.py` argparse tree
- [ ] **Delete** `get_help()` method from `stata_client.py`
- [ ] **Delete** early interception block in `run_command_streaming()`
- [ ] **Delete** `_extract_help_topic()` static method
- [ ] **Delete** `_HELP_TOPIC_RE` and `_HELP_BARE_RE` regex constants
- [ ] **Verify** `smcl_to_markdown()` no longer needs the help-specific code path
- [ ] **Rewrite** `plugin/skills/stata-help/SKILL.md` to reference `stata help <topic>`
- [ ] **Test** all topics: built-in, documented, dynamic, nonexistent
- [ ] **Test** output limiting: 50, 100, 200 lines; 4K, 8K, 16K chars
- [ ] **Test** section extraction: syntax, options, examples, summary
- [ ] **Test** terminal code stripping with various locale/TERM settings
- [ ] **Benchmark** latency: target <100ms for common topics
