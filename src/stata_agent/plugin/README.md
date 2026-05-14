# stata-agent plugin

This directory contains the plugin package bundled within the stata-agent wheel. After installation, it is accessible via `importlib.resources.files("stata_agent") / "plugin"`.

## Contents

- `.claude-plugin/` — Claude Code plugin manifest and marketplace
- `.codex-plugin/` — Codex plugin manifest
- `.agents/` — Generic agent skills marketplace
- `agents/` — Agent persona definitions
- `hooks/` — SessionStart hooks
- `skills/` — SKILL.md files (real directory, no symlinks)
- `gemini-extension.json` — Gemini CLI extension

All JSON manifests use `{{VERSION}}` as a placeholder, replaced at runtime by `skills_installer.py`.

Agent-side symlinks are created by `stata-agent install-skills` at registration time, never inside the wheel.
