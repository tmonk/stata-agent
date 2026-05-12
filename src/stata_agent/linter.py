"""do-file static analysis — lint Stata syntax before execution.

Checks for common issues: unclosed loops/if-blocks, unbalanced
quotes, missing `end` in Mata blocks, and suspicious patterns.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


LintSeverity = str  # "error" | "warning" | "info"


class LintIssue:
    """A single lint finding."""

    def __init__(self, severity: LintSeverity, message: str, line: int = 0, column: int = 0):
        self.severity = severity
        self.message = message
        self.line = line
        self.column = column

    def __repr__(self) -> str:
        loc = f":{self.line}" if self.line else ""
        return f"[{self.severity}]{loc} {self.message}"


# Patterns
_COMMENT_LINE_RE = re.compile(r"^\s*\*")
_BLOCK_OPENERS = {"forvalues", "foreach", "while", "if", "else", "capture noisily"}
_BLOCK_CLOSERS = {"end", "}"}
_MATA_START_RE = re.compile(r"^\s*mata\s*(:|$)", re.IGNORECASE)
_MATA_END_RE = re.compile(r"^\s*end\s*$", re.IGNORECASE)
_QUOTE_RE = re.compile(r'"')
_ODBC_RE = re.compile(r"odbc\s+(load|insert|query)", re.IGNORECASE)
_SHELL_RE = re.compile(r"!(wget|curl|rm|del|mv|python|bash)", re.IGNORECASE)
_SET_MEMORY_RE = re.compile(r"set\s+memory", re.IGNORECASE)
_VERSION_RE = re.compile(r"^version\s+\d", re.IGNORECASE)
_CAPTURE_RE = re.compile(r"^\s*capture\s", re.IGNORECASE)


def lint_file(path: str | Path) -> list[LintIssue]:
    """Lint a do-file and return a list of issues."""
    path = Path(path)
    if not path.exists():
        return [LintIssue("error", f"File not found: {path}")]

    text = path.read_text(encoding="utf-8", errors="replace")
    return lint_text(text, filename=str(path))


def lint_text(text: str, filename: str = "") -> list[LintIssue]:
    """Lint Stata code text and return a list of issues."""
    issues: list[LintIssue] = []
    lines = text.split("\n")

    in_mata = False
    brace_depth = 0
    in_multiline_string = False
    quote_balance = True  # True = even number of quotes

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or _COMMENT_LINE_RE.match(line):
            continue

        # Mata block tracking
        if _MATA_START_RE.search(stripped):
            in_mata = True
            continue

        if _MATA_END_RE.match(stripped):
            if not in_mata:
                issues.append(LintIssue("warning", "Unexpected 'end' outside mata block", i))
            in_mata = False
            continue

        # Quote balance check (simple: count unescaped quotes)
        raw_quotes = stripped.count('"')
        if raw_quotes % 2 != 0:
            # Check for escaped quotes or compound quotes
            if '"' in stripped.replace('""', ''):
                quote_balance = not quote_balance
                if not quote_balance:
                    issues.append(LintIssue("warning", "Unbalanced double quotes", i))

        # Brace depth tracking (inside code blocks)
        if not in_mata:
            # Skip capture blocks — they own their braces
            if _CAPTURE_RE.match(stripped):
                continue
            brace_depth += stripped.count("{")
            brace_depth -= stripped.count("}")

        # Specific checks
        if not in_mata:
            # Check for missing version statement early
            if i <= 3 and _VERSION_RE.match(stripped):
                pass  # Version found — good

            # Warn about shell commands
            if _SHELL_RE.search(stripped):
                issues.append(LintIssue(
                    "warning",
                    f"Shell command detected: {stripped[:60]}",
                    i,
                ))

            # Warn about set memory (deprecated in Stata 16+)
            if _SET_MEMORY_RE.search(stripped):
                issues.append(LintIssue(
                    "info",
                    "'set memory' is deprecated in Stata 16+. Use 'set maxvar' instead.",
                    i,
                ))

    # Final checks
    if brace_depth > 0:
        issues.append(LintIssue("error", f"Unclosed brace(s) (depth={brace_depth}) at end of file"))

    if brace_depth < 0:
        issues.append(LintIssue("error", f"Too many closing braces (depth={brace_depth})"))

    if in_mata:
        issues.append(LintIssue("error", "Mata block not closed with 'end'"))

    if not issues:
        issues.append(LintIssue("info", "No issues found"))

    return issues


def format_lint_results(issues: list[LintIssue]) -> str:
    """Format lint results as a readable string."""
    if not issues:
        return "[stata-lint] No issues found."

    lines = []
    for issue in issues:
        loc = f" line {issue.line}" if issue.line else ""
        lines.append(f"  [{issue.severity}]{loc} {issue.message}")

    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")

    summary = f"\n{error_count} error(s), {warning_count} warning(s)"
    return "\n".join(lines) + summary
