# Assumptions and Decisions

This file documents sensible defaults used for open questions in the implementation plan.

## 1. Worker domain
`stata-agent-install.tdmonk.com` — assumed available. Worker code is written but deployment is out of scope for this phase.

## 2. PyPI package name
`stata-agent` — assumed unclaimed on PyPI. If taken, the fallback is `stata_agent_cli` and would require updating pyproject.toml entry point, Worker URLs, and workbench installer code.

## 3. Binary name collision
`stata-agent` does not conflict with Stata Corp's executables (`stata`, `stata-mp`, `stata-se`, `stata-be`). No fallback or alias needed.

## 4. Windows uv tool bin directory
Discovered dynamically via `uv tool dir --bin` at runtime. Not hard-coded to `%APPDATA%\uv\bin` or `%USERPROFILE%\.local\bin`.

## 5. GitHub repository structure
stata-agent currently lives as a standalone repo at `~/projects/stata-agent`. The plan references `tmonk/mcp-stata` with `INSTALL_SUBPATH=stata-agent`. The Worker `GITHUB_REPO` wrangler var is set to `tmonk/mcp-stata`.

## 6. `stata-agent doctor --json`
Implemented in cli.py and verify.py. This is the single source of truth consumed by the installer shell script.

## 7. Plugin relocation
Skills moved from `~/projects/stata-agent/skills/` to `src/stata_agent/plugin/skills/`. Old `skills/` directory removed. No internal relative symlinks in the wheel.

## 8. `claude plugin` CLI availability
`install-skills` uses `shutil.which("claude")` guard and degrades gracefully to symlink-only install if Claude Code is absent.

## 9. Re-exec on Windows
Uses `subprocess.run + sys.exit` instead of `os.execv` (unreliable on Windows CPython).

## 10. `/latest.json` implementation
Worker fetches latest version from PyPI periodically (configurable via `LATEST_VERSION` env var). Denylist writable via env var or manual update.

## 11. Wheel symlinks
Confirmed via CI wheel inspection that hatchling includes plugin files. Internal symlinks removed from the plugin package.

## 12. Proxy/firewall support
uv bootstrap, PyPI/Worker checks, installer downloads, and telemetry all respect `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY`.

## 13. Fish shell
`fish_add_path` used in `ensure_path()` when `~/.config/fish/config.fish` exists. Fish version compatibility assumed for the `fish_add_path` builtin.

## 14. `mcp-client.js` PyPI version reference
Obsolete. The workbench updater delegates to `stata-agent upgrade --quiet` and does not replicate PyPI fetch logic.
