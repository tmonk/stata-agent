#!/usr/bin/env bash
# mock_uv.sh — Fake uv binary for testing install.sh --dry-run and unit tests.
# Records invocations to MOCK_UV_LOG and returns configurable exit codes.
#
# Usage in tests:
#   export MOCK_UV_EXIT=0          # Exit code to return
#   export MOCK_UV_VERSION="uv 0.6.0"    # Version string (--version)
#   export MOCK_UV_TOOL_DIR_BIN="/custom/bin/dir"  # Custom bin dir
#   export MOCK_UV_TOOL_LIST="stata-agent 0.1.0"   # uv tool list output
#   PATH="tests/install/helpers:$PATH" bash install.sh --dry-run

LOG_FILE="${MOCK_UV_LOG:-/tmp/mock_uv.log}"

case "${1:-}" in
  --version)
    echo "${MOCK_UV_VERSION:-uv 0.6.0}"
    ;;
  tool)
    case "${2:-}" in
      dir)
        if [ "${3:-}" = "--bin" ]; then
          echo "${MOCK_UV_TOOL_DIR_BIN:-${HOME}/.local/bin}"
        else
          echo "${MOCK_UV_TOOL_DIR:-${HOME}/.local/share/uv/tools}"
        fi
        ;;
      list)
        echo "${MOCK_UV_TOOL_LIST:-}"
        ;;
      install|upgrade|uninstall)
        echo "${2} ${3:-} ${4:-} ${5:-}" >> "$LOG_FILE"
        exit "${MOCK_UV_EXIT:-0}"
        ;;
      *)
        echo "${1} ${2} ${3:-}" >> "$LOG_FILE"
        exit "${MOCK_UV_EXIT:-0}"
        ;;
    esac
    ;;
  python)
    # Fake Python for install commands
    exit "${MOCK_UV_EXIT:-0}"
    ;;
  *)
    echo "${1:-} ${2:-} ${3:-}" >> "$LOG_FILE"
    exit "${MOCK_UV_EXIT:-0}"
    ;;
esac
