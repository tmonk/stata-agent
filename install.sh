#!/usr/bin/env bash
# stata-agent installer for Linux and macOS.
# Bootstraps uv, installs stata-agent via uv tool install, registers skills,
# verifies with doctor --json, and sends telemetry.
# Fully idempotent — re-running always produces a correct, up-to-date installation.
set -euo pipefail

# ── Formatting ────────────────────────────────────────────────────────────────
BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; MAGENTA=''; RESET=''
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD='\033[1m'; DIM='\033[2m'; RED='\033[31m'; GREEN='\033[32m'
  YELLOW='\033[33m'; BLUE='\033[34m'; MAGENTA='\033[35m'; CYAN='\033[36m'
  RESET='\033[0m'
fi

ACTION_LABEL="Installation"
VERBOSE_MODE=0
SCRIPT_VERSION="0.1.0"

# ── Globals ──────────────────────────────────────────────────────────────────
INSTALL_HOST="stata-agent-install.tdmonk.com"
TELEMETRY_URL="https://${INSTALL_HOST}/telemetry"
GITHUB_REPO_URL="https://github.com/tmonk/mcp-stata/tree/main/stata-agent"
LOG_FILE="${HOME}/.local/state/stata-agent/install.log"
INSTALL_ID=""
USER_ID=""

paint() { local style="$1"; shift; printf '%b%s%b' "$style" "$*" "$RESET"; }
blank() { printf '\n'; }
say() { printf "%b%s%b %s\n" "${CYAN}${BOLD}" "›" "${RESET}" "$1"; }
ok()  { printf "%b%s%b %s\n" "${GREEN}${BOLD}" "✓" "${RESET}" "$1"; }
warn() { printf "%b%s%b %s\n" "${YELLOW}${BOLD}" "!" "${RESET}" "$1" >&2; }
err() {
  local msg="$1"; local log_tail=""
  if [ -f "$LOG_FILE" ]; then log_tail="$(tail -c 4000 "$LOG_FILE" 2>/dev/null || true)"; fi
  send_telemetry "install_failure" "${msg}" "$log_tail" || true
  show_failure "$msg"
  exit 1
}
rule() { paint "$1" "======================================"; printf '\n'; }
detail() { printf "    %b%s%b %s\n" "${DIM}" "•" "${RESET}" "$1"; }

show_header() {
  cat <<EOF
$(paint "${MAGENTA}${BOLD}" "======================================")
$(paint "${CYAN}${BOLD}" "   ___ __  __          __           ___              __")
$(paint "${CYAN}${BOLD}" "  / __\`/ /_/ /_____ _  / /_  ___ _  / _ \\ ___ _  ___ / /_")
$(paint "${CYAN}${BOLD}" "  \\__ \\/ __/ __/ _ \`/ / __/ / _ \`/ / // // _ \`/ / _ \`/ __/")
$(paint "${CYAN}${BOLD}" " /___/\\__/\\__/\\_,_/  \\__/  \\_,_/ /____/ \\_, /  \\_,_/\\__/")
$(paint "${CYAN}${BOLD}" "                                       /___/      installer")
$(paint "${MAGENTA}${BOLD}" "======================================")
EOF
  printf "%b%s%b %s\n" "${DIM}" "host   " "${RESET}" "$(uname -srm 2>/dev/null || echo unknown)"
  printf "%b%s%b %s\n" "${DIM}" "shell  " "${RESET}" "bash ${BASH_VERSION:-?}"
  printf "%b%s%b %s\n" "${DIM}" "user   " "${RESET}" "$(id -un 2>/dev/null) (uid=$(id -u))"
  printf "%b%s%b %s\n" "${DIM}" "script " "${RESET}" "v${SCRIPT_VERSION}"
  [ "${DRY_RUN:-0}" -eq 1 ] && printf "%b%s%b\n" "${YELLOW}${BOLD}" "[dry-run]  No filesystem mutations" "${RESET}"
  blank
}

show_success() {
  blank
  rule "${GREEN}${BOLD}"
  printf "%b%s%b\n" "${GREEN}${BOLD}" "STATA-AGENT IS LIVE" "${RESET}"
  rule "${GREEN}${BOLD}"
  printf "  %b%s%b\n" "${CYAN}${BOLD}" "Verify:" "${RESET}"
  printf "    stata-agent --version\n"
  printf "    stata-agent doctor --json\n"
  blank
  printf "%b%s%b %s\n" "${DIM}" "repo   " "${RESET}" "${GITHUB_REPO_URL}"
  printf "%b%s%b %s\n" "${DIM}" "log    " "${RESET}" "$LOG_FILE"
}

show_failure() {
  local message="$1"
  blank
  printf "%b%s%b %s\n" "${RED}${BOLD}" "✖" "${RESET}" "$message" >&2
  rule "${RED}" >&2
  printf "%b%s%b\n" "${RED}${BOLD}" "FAILED: ${ACTION_LABEL} COULD NOT BE COMPLETED" "${RESET}" >&2
  rule "${RED}" >&2
  printf >&2 "%b%s%b %s\n" "${DIM}" "log    " "${RESET}" "$LOG_FILE"
  printf >&2 "%b%s%b %s\n" "${DIM}" "report " "${RESET}" "https://github.com/tmonk/mcp-stata/issues/new"
}

# ── Telemetry ────────────────────────────────────────────────────────────────
json_escape() { printf '%s' "$1" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$1"; }

make_install_id() { python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || echo "$(date +%s)-$$"; }

get_user_id() {
  local f="$HOME/.local/state/stata-agent/user_id"
  if [ -f "$f" ]; then cat "$f"; return 0; fi
  local id; id="$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || echo "$(date +%s)-$$")"
  mkdir -p "$(dirname "$f")" 2>/dev/null || true
  echo "$id" > "$f" 2>/dev/null || true
  echo "$id"
}

send_telemetry() {
  local event="$1"; local error_code="${2:-}"; local log_tail="${3:-}"
  [ "${TELEMETRY_DISABLED:-0}" -eq 1 ] && return 0
  [ "${DRY_RUN:-0}" -eq 1 ] && return 0
  command -v curl >/dev/null 2>&1 || return 0

  local os_name; os_name="$(uname -s 2>/dev/null || echo unknown)"
  local os_arch; os_arch="$(uname -m 2>/dev/null || echo unknown)"
  local distro=""
  if [ -f /etc/os-release ]; then distro="$(grep ^ID= /etc/os-release | cut -d= -f2 | tr -d '"')"; fi

  local action="install"
  case "$event" in
    upgrade_*) action="upgrade" ;;
    uninstall_*) action="uninstall" ;;
  esac

  local install_source="${STATA_AGENT_INSTALL_SOURCE:-direct}"

  local payload
  payload=$(cat <<PAYLOAD
{
  "event": "$(json_escape "$event")",
  "action": "$(json_escape "$action")",
  "stage": "$(json_escape "${STAGE:-}")",
  "file": "install.sh",
  "install_source": "$(json_escape "$install_source")",
  "scope": "",
  "os": "$(json_escape "$os_name")",
  "distro": "$(json_escape "$distro")",
  "arch": "$(json_escape "$os_arch")",
  "error_code": "$(json_escape "$error_code")",
  "install_id": "$(json_escape "$INSTALL_ID")",
  "user_id": "$(json_escape "$USER_ID")",
  "script_version": "$(json_escape "$SCRIPT_VERSION")",
  "schema_version": "1",
  "log_tail": $(json_escape "$log_tail")
}
PAYLOAD
)

  curl -sSf -X POST "$TELEMETRY_URL" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    --max-time 5 \
    >/dev/null 2>&1 || true
}

# ── uv bootstrap ─────────────────────────────────────────────────────────────
ensure_uv() {
  STAGE="ensure_uv"
  if command -v uv >/dev/null 2>&1; then
    ok "uv $(uv --version 2>/dev/null | head -1 || echo 'found')"
    return 0
  fi
  say "Bootstrapping uv (Python package manager)..."
  [ "${DRY_RUN:-0}" -eq 1 ] && { detail "[dry-run] curl -LsSf https://astral.sh/uv/install.sh | sh"; return 0; }
  curl -LsSf https://astral.sh/uv/install.sh | sh || err "Failed to install uv"
  export PATH="$HOME/.local/bin:$PATH"
  ok "uv installed"
}

# ── Package install/upgrade ──────────────────────────────────────────────────
install_or_upgrade_package() {
  STAGE="install_package"
  if [ "${UPGRADE_MODE:-0}" -eq 1 ]; then
    ACTION_LABEL="Upgrade"
    say "Upgrading stata-agent..."
    [ "${DRY_RUN:-0}" -eq 1 ] && { detail "[dry-run] uv tool upgrade stata-agent"; return 0; }
    uv tool upgrade stata-agent || err "uv tool upgrade stata-agent failed"
    ok "Upgraded to $(stata-agent --version 2>/dev/null | head -1 || echo 'latest')"
    send_telemetry "upgrade_start" "" ""
    send_telemetry "upgrade_success" "" ""
  elif [ "${UNINSTALL_MODE:-0}" -eq 1 ]; then
    ACTION_LABEL="Uninstall"
    say "Uninstalling stata-agent..."
    [ "${DRY_RUN:-0}" -eq 1 ] && { detail "[dry-run] stata-agent install-skills --uninstall --quiet"; detail "[dry-run] uv tool uninstall stata-agent"; return 0; }
    stata-agent install-skills --uninstall --quiet 2>/dev/null || true
    uv tool uninstall stata-agent || warn "stata-agent was not installed via uv tool"
    ok "stata-agent uninstalled"
    send_telemetry "uninstall_start" "" ""
    send_telemetry "uninstall_success" "" ""
  elif uv tool list 2>/dev/null | grep -q "^stata-agent "; then
    ACTION_LABEL="Upgrade"
    say "stata-agent already installed — upgrading"
    [ "${DRY_RUN:-0}" -eq 1 ] && { detail "[dry-run] uv tool upgrade stata-agent"; return 0; }
    uv tool upgrade stata-agent || err "uv tool upgrade stata-agent failed"
    ok "Upgraded to $(stata-agent --version 2>/dev/null | head -1)"
    send_telemetry "upgrade_start" "" ""
    send_telemetry "upgrade_success" "" ""
  else
    ACTION_LABEL="Installation"
    local pkg="stata-agent"
    [ -n "${PINNED_VERSION:-}" ] && pkg="stata-agent==${PINNED_VERSION}"
    say "Installing ${pkg} via uv tool install..."
    [ "${DRY_RUN:-0}" -eq 1 ] && { detail "[dry-run] uv tool install ${pkg}"; return 0; }
    uv tool install "$pkg" || err "uv tool install $pkg failed"
    ok "Installed $(stata-agent --version 2>/dev/null | head -1)"
  fi
}

# ── PATH configuration ───────────────────────────────────────────────────────
ensure_path() {
  STAGE="ensure_path"
  [ "${NO_PATH:-0}" -eq 1 ] && { detail "PATH modification skipped (--no-path)"; return 0; }

  local bin_dir
  bin_dir="$(uv tool dir --bin 2>/dev/null)" || bin_dir="${HOME}/.local/bin"

  if [[ ":$PATH:" == *":${bin_dir}:"* ]]; then
    detail "uv tool bin directory already on PATH: ${bin_dir}"
    return 0
  fi

  say "Adding uv tool bin directory to PATH..."

  local added=0
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    detail "[dry-run] Would add ${bin_dir} to shell profile"
    return 0
  fi

  # Support bash, zsh, fish, and profile
  for rc in "${HOME}/.zshrc" "${HOME}/.bashrc" "${HOME}/.profile"; do
    if [ -f "$rc" ]; then
      if ! grep -qF "stata-agent" "$rc" 2>/dev/null; then
        printf '\n# stata-agent\nexport PATH="%s:$PATH"\n' "$bin_dir" >> "$rc"
        ok "Added ${bin_dir} to ${rc}"
        added=1
      fi
      break
    fi
  done

  # fish shell: use fish_add_path
  local fish_config="${HOME}/.config/fish/config.fish"
  if command -v fish &>/dev/null && [ -f "$fish_config" ]; then
    if ! grep -qF "stata-agent" "$fish_config" 2>/dev/null; then
      printf '\n# stata-agent\nfish_add_path "%s"\n' "$bin_dir" >> "$fish_config"
      ok "Added ${bin_dir} to ${fish_config}"
      added=1
    fi
  fi

  if [ "$added" -eq 0 ]; then
    warn "Could not find a shell RC file to update. Add ${bin_dir} to PATH manually."
  fi

  export PATH="${bin_dir}:${PATH}"
}

# ── Skills registration ──────────────────────────────────────────────────────
install_skills() {
  STAGE="install_skills"
  [ "${SKIP_SKILLS:-0}" -eq 1 ] && { detail "Skills registration skipped"; return 0; }

  say "Registering skills with AI agents..."
  [ "${DRY_RUN:-0}" -eq 1 ] && { detail "[dry-run] stata-agent install-skills"; return 0; }

  if ! stata-agent install-skills 2>&1 | while IFS= read -r line; do
      printf "   %b%s%b %s\n" "${DIM}" "•" "${RESET}" "$line"
    done; then
    warn "Skills registration encountered issues. Run: stata-agent install-skills --verbose"
  else
    ok "Skills registered with detected agents"
  fi
}

# ── Verification ─────────────────────────────────────────────────────────────
verify_install() {
  STAGE="verify_install"
  hash -r 2>/dev/null || true

  say "Verifying installation..."

  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    detail "[dry-run] stata-agent --version"
    detail "[dry-run] stata-agent doctor --json"
    return 0
  fi

  # Check for the stata-agent binary
  if ! command -v stata-agent &>/dev/null; then
    err "stata-agent binary not found on PATH after install. Open a new terminal and run: stata-agent doctor"
  fi

  # Confirm this is stata-agent, not a Stata Corp binary
  local version_out
  version_out="$(stata-agent --version 2>&1)" || err "stata-agent --version failed"
  if ! echo "$version_out" | grep -q "stata.agent\|stata_agent"; then
    warn "stata-agent binary found but may not be stata-agent: ${version_out}"
  fi

  # Structured doctor output
  local doctor_out
  doctor_out="$(stata-agent doctor --json 2>&1)" || warn "stata-agent doctor reported issues (see above)"
  ok "stata-agent doctor passed"

  # Warn if PATH change requires a new terminal
  if ! command -v stata-agent &>/dev/null 2>&1; then
    warn "stata-agent installed but not visible in current shell. Open a new terminal or run: source ~/.zshrc"
  fi
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
  # Parse flags first
  DRY_RUN=0; VERBOSE_MODE=0; UPGRADE_MODE=0; UNINSTALL_MODE=0; PURGE_MODE=0
  NO_AUTO_UPGRADE_FIRST=0; NO_PATH=0; SKIP_SKILLS=0; PINNED_VERSION=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) DRY_RUN=1; shift ;;
      --verbose) VERBOSE_MODE=1; shift ;;
      --upgrade) UPGRADE_MODE=1; shift ;;
      --uninstall) UNINSTALL_MODE=1; shift ;;
      --purge) PURGE_MODE=1; UNINSTALL_MODE=1; shift ;;
      --version) PINNED_VERSION="$2"; shift 2 ;;
      --no-auto-upgrade-on-first-run) NO_AUTO_UPGRADE_FIRST=1; shift ;;
      --no-path) NO_PATH=1; shift ;;
      --help|-h)
        cat <<HELP
Usage: bash install.sh [FLAGS]

Flags:
  --upgrade        Upgrade existing installation
  --uninstall      Remove stata-agent
  --purge          Remove everything including user state/config
  --version X      Install specific version (e.g., --version 1.2.3)
  --dry-run        Print commands without executing
  --verbose        Show subprocess output
  --no-path        Skip PATH modification
  --no-auto-upgrade-on-first-run  Skip auto-upgrade on first run
  --help           Show this help

Environment:
  STATA_AGENT_INSTALL_SOURCE    Tag telemetry source (direct|workbench|ci)
  STATA_AGENT_TELEMETRY_DISABLED  Set to 1 to disable telemetry
  NO_COLOR                       Set to disable colored output
HELP
        exit 0 ;;
      *) echo "Unknown flag: $1 (use --help)"; exit 1 ;;
    esac
  done

  # Setup logging
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
  exec 3>&1 4>&2
  if [ "${DRY_RUN:-0}" -ne 1 ]; then
    exec 1> >(tee -a "$LOG_FILE") 2>&1
  fi

  # Setup telemetry identifiers
  INSTALL_ID="$(make_install_id)"
  USER_ID="$(get_user_id)"

  show_header
  STAGE="install_start"
  send_telemetry "install_start" "" "" || true

  # Installation pipeline
  ensure_uv
  install_or_upgrade_package

  if [ "${UNINSTALL_MODE:-0}" -eq 1 ]; then
    if [ "${PURGE_MODE:-0}" -eq 1 ]; then
      STAGE="purge"
      say "Purging user state..."
      [ "${DRY_RUN:-0}" -eq 1 ] && { detail "[dry-run] Would remove ~/.local/state/stata-agent"; }
      [ "${DRY_RUN:-0}" -ne 1 ] && rm -rf "${HOME}/.local/state/stata-agent" 2>/dev/null || true
      [ "${DRY_RUN:-0}" -ne 1 ] && rm -rf "${HOME}/.cache/stata-agent" 2>/dev/null || true
    fi
    send_telemetry "uninstall_success" "" "" || true
    ok "Uninstall complete"
    return 0
  fi

  ensure_path
  install_skills
  verify_install

  STAGE="install_success"
  send_telemetry "install_success" "" "" || true
  show_success
}

main "$@"
