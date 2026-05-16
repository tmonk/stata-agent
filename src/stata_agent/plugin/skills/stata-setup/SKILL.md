---
name: stata-setup
description: Install, configure, update, or verify stata-agent and its Stata environment. Activate when users ask to set up the Stata toolkit or troubleshoot the installation.
---

# Setup and Verification

Use the installer and verification flow instead of hand-writing per-agent config unless the user explicitly asks for manual steps.

## Preferred Install Commands

Install the latest version:

```bash
curl -LsSf https://stata-agent-install.tdmonk.com/install.sh | bash
```

Verify the installation:

```bash
stata-agent doctor
```

Start a daemon session:

```bash
stata-agent daemon start
```

Run a quick test:

```bash
stata-agent run "display 1+1"
```

## What the Installer Does

- Installs the `stata-agent` CLI binary
- Sets up cache directories at `~/.cache/stata-agent/`
- Registers skills with compatible AI agents
- Supports auto-upgrade on session start

## Verification Standard

When the user asks whether setup is complete, verify more than "the file exists":

1. Stata discovery and edition (`stata-agent discover`)
2. Python >= 3.11
3. Daemon health (`stata-agent daemon status`)
4. Basic execution (`stata-agent run "display 2+2"`)
5. Graph-export readiness
6. Log-path emission for command output
7. Package availability for `reghdfe` and `gtools` if needed

If live verification is not possible on the current machine, state exactly what remains unverified.

## CLI Reference

| Command | Description |
|---|---|
| `stata doctor` | Full environment check (Python, Stata, pystata-x, daemon) |
| `stata discover` | Find Stata installations |
| `stata daemon start [--session NAME] [--mock]` | Start daemon for persistent session |
| `stata daemon stop [--session NAME]` | Stop daemon |
| `stata daemon status [--session NAME]` | Check daemon health |

## Requirements

- Python >= 3.11
- Stata (any edition with `stata-se` binary)
- pystata (for stateful session) or subprocess fallback

## Getting Started

1. Run `stata doctor` to check your environment.
2. Run `stata discover` to find Stata.
3. Run `stata daemon start` to start the daemon.
4. Run `stata run "display 1+1"` to verify everything works.

## Mock Mode

Use `stata daemon start --mock` for CI/testing without a Stata license.

## Troubleshooting

- If Stata is not discovered, tell the user to set `STATA_PATH`.
- If the daemon fails to start, use the **stata-environment-diagnose** skill.
- Use `stata-agent doctor` for a full environment report.
