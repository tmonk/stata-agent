# stata-setup

Initial environment setup and verification for Stata.

## Commands

- `stata doctor` — Full environment check
- `stata discover` — Find Stata installations
- `stata daemon start [--session NAME] [--mock]` — Start daemon

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
