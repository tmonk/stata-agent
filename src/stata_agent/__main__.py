"""Allow `python -m stata_agent` to delegate to the CLI."""

from stata_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
