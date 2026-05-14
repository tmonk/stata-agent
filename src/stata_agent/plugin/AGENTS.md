# stata-agent

CLI-native Stata integration for AI agents. Run code, inspect data, retrieve results, export graphs, and test do-files.

## Available skills

| Skill | Description |
|---|---|
| `/stata-run` | Execute Stata code or do-files |
| `/stata-inspect` | Describe, summarize, list, or export dataset |
| `/stata-results` | Retrieve r(), e(), and s() stored results |
| `/stata-graph` | List and export Stata graphs |
| `/stata-log` | Read and search session logs |
| `/stata-help` | Access Stata help system |
| `/stata-lint` | Lint do-files for errors |
| `/stata-setup` | Set up Stata environment |
| `/stata-test` | Run statest test suites |

## Quick start

```bash
# Install
curl -LsSf https://stata-agent-install.tdmonk.com/install.sh | bash

# Start a daemon session
stata-agent daemon start --session default

# Run code
stata-agent run "sysuse auto; summarize price"

# Get results
stata-agent results --return r

# Export graph
stata-agent graph export --name Graph --format pdf
```

## Environment

- Cache: `~/.cache/stata-agent/`
- State: `~/.local/state/stata-agent/`
- Env: `STATA_AGENT_NO_AUTO_UPGRADE=1` disables auto-update
- Env: `STATA_AGENT_PATH` overrides CLI binary path
