# stata-lint

Static analysis for Stata do-files.

## Commands

- `stata lint /path/to/file.do` — Check a do-file for issues

## Checks

- Unclosed braces (`{` / `}`)
- Unclosed Mata blocks
- Shell commands (`!wget`, `!curl`, etc.)
- Deprecated `set memory`
- Unbalanced quotes

## Exit Code

Returns 1 if any errors are found, 0 otherwise.
