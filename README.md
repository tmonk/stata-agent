# stata-agent

CLI-native Stata integration for AI agents. Run code, inspect data, retrieve results, export graphs, and test do-files.

## Quick Start

```bash
curl -LsSf https://stata-agent-install.tdmonk.com/install.sh | bash
```

## CLI Commands

- `stata-agent daemon start` — Start the Stata daemon
- `stata-agent run "code"` — Execute Stata code
- `stata-agent doctor --json` — Check environment health
- `stata-agent install-skills` — Register skills with AI agents
- `stata-agent upgrade` — Update to latest version

## Development

```bash
uv run stata-agent --help
uv run pytest tests/
```
