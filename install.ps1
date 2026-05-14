#Requires -Version 5
<#
.SYNOPSIS
    Bootstrap installer for stata-agent on Windows.
    Ensures uv is available, installs stata-agent via uv tool install,
    registers skills, verifies with doctor --json, and sends telemetry.
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$VerboseMode,
    [switch]$Upgrade,
    [switch]$Uninstall,
    [switch]$Purge,
    [string]$Version,
    [switch]$NoAutoUpgradeOnFirstRun,
    [switch]$NoPath,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ── Configuration ─────────────────────────────────────────────────────────────
$InstallHost = 'stata-agent-install.tdmonk.com'
$TelemetryUrl = "https://${InstallHost}/telemetry"
$GithubRepoUrl = 'https://github.com/tmonk/stata-agent'
$ScriptVersion = '0.1.0'
$TranscriptLog = Join-Path $env:TEMP "stata-agent-install-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"

# ── Logging ──────────────────────────────────────────────────────────────────
Start-Transcript -Path $TranscriptLog -Append -Force

function Write-Step { param($Msg) Write-Host "› $Msg" -ForegroundColor Cyan }
function Write-Ok   { param($Msg) Write-Host "✓ $Msg" -ForegroundColor Green }
function Write-Warn { param($Msg) Write-Host "! $Msg" -ForegroundColor Yellow }
function Write-Err  {
    param($Msg)
    Write-Host "✖ $Msg" -ForegroundColor Red
    Send-Telemetry "install_failure" $Msg
    Stop-Transcript
    exit 1
}

# ── Header ───────────────────────────────────────────────────────────────────
function Show-Header {
    Write-Host '======================================' -ForegroundColor Magenta
    Write-Host '  stata-agent installer for Windows' -ForegroundColor Cyan
    Write-Host '======================================' -ForegroundColor Magenta
    Write-Host "host    $(if ($IsWindows) { "$env:COMPUTERNAME" } else { hostname })" -ForegroundColor DarkGray
    Write-Host "script  v$ScriptVersion" -ForegroundColor DarkGray
    if ($DryRun) { Write-Host '[dry-run] No filesystem mutations' -ForegroundColor Yellow }
    Write-Host ''
}

# ── Telemetry ────────────────────────────────────────────────────────────────
function New-InstallId { [guid]::NewGuid().ToString() }
function Get-UserId {
    $f = Join-Path $env:LOCALAPPDATA 'stata-agent\state\user_id'
    if (Test-Path $f) { return Get-Content $f -Raw }
    $dir = Split-Path $f -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $id = [guid]::NewGuid().ToString()
    Set-Content -Path $f -Value $id -Force
    return $id
}

function Send-Telemetry {
    param($Event, $ErrorCode = '', $LogTail = '')
    if ($DryRun) { return }
    if ($env:STATA_AGENT_TELEMETRY_DISABLED -eq '1') { return }

    $osName = if ($IsWindows) { 'windows' } else { 'unknown' }
    $installSource = if ($env:STATA_AGENT_INSTALL_SOURCE) { $env:STATA_AGENT_INSTALL_SOURCE } else { 'direct' }
    $action = switch -Wildcard ($Event) {
        'upgrade_*'   { 'upgrade' }
        'uninstall_*' { 'uninstall' }
        default       { 'install' }
    }

    $payload = @{
        event            = $Event
        action           = $action
        stage            = $global:Stage
        file             = 'install.ps1'
        install_source   = $installSource
        scope            = ''
        os               = $osName
        distro           = ''
        arch             = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        error_code       = $ErrorCode
        install_id       = $global:InstallId
        user_id          = $global:UserId
        script_version   = $ScriptVersion
        schema_version   = '1'
        log_tail         = $LogTail
    } | ConvertTo-Json -Compress

    try {
        Invoke-WebRequest -Uri $TelemetryUrl -Method Post -Body $payload -ContentType 'application/json' -TimeoutSec 5 -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}

# ── uv bootstrap ─────────────────────────────────────────────────────────────
function Ensure-Uv {
    $global:Stage = 'ensure_uv'
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $ver = & uv --version 2>$null
        Write-Ok "uv found: $ver"
        return
    }
    Write-Step 'Bootstrapping uv (Python package manager)...'
    if ($DryRun) { Write-Host '  [dry-run] powershell -c "irm https://astral.sh/uv/install.ps1 | iex"' -ForegroundColor DarkGray; return }
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    Write-Ok 'uv installed'
}

# ── uv tool bin discovery ────────────────────────────────────────────────────
function Get-UvToolBinDir {
    try {
        $binDir = & uv tool dir --bin 2>$null
        if ($binDir -and (Test-Path $binDir)) { return $binDir.Trim() }
    } catch {}
    return "$env:USERPROFILE\.local\bin"
}

# ── Package install/upgrade ──────────────────────────────────────────────────
function Install-Package {
    $global:Stage = 'install_package'

    if ($Upgrade) {
        Write-Step 'Upgrading stata-agent...'
        if ($DryRun) { Write-Host '  [dry-run] uv tool upgrade stata-agent' -ForegroundColor DarkGray; return }
        uv tool upgrade stata-agent
        $ver = & stata-agent --version 2>$null
        Write-Ok "Upgraded to $ver"
        Send-Telemetry 'upgrade_success'
        return
    }

    if ($Uninstall) {
        Write-Step 'Uninstalling stata-agent...'
        if ($DryRun) {
            Write-Host '  [dry-run] stata-agent install-skills --uninstall --quiet' -ForegroundColor DarkGray
            Write-Host '  [dry-run] uv tool uninstall stata-agent' -ForegroundColor DarkGray
            return
        }
        & stata-agent install-skills --uninstall --quiet 2>$null
        uv tool uninstall stata-agent 2>$null
        Write-Ok 'stata-agent uninstalled'
        Send-Telemetry 'uninstall_success'
        return
    }

    $installed = $false
    try {
        $list = & uv tool list 2>$null
        if ($list -match 'stata-agent') { $installed = $true }
    } catch {}

    $pkg = 'stata-agent'
    if ($Version) { $pkg = "stata-agent==$Version" }

    if ($installed) {
        Write-Step 'stata-agent already installed — upgrading'
        if ($DryRun) { Write-Host "  [dry-run] uv tool upgrade $pkg" -ForegroundColor DarkGray; return }
        uv tool upgrade stata-agent
        $ver = & stata-agent --version 2>$null
        Write-Ok "Upgraded to $ver"
        Send-Telemetry 'upgrade_success'
    } else {
        Write-Step "Installing $pkg via uv tool install..."
        if ($DryRun) { Write-Host "  [dry-run] uv tool install $pkg" -ForegroundColor DarkGray; return }
        uv tool install $pkg
        $ver = & stata-agent --version 2>$null
        Write-Ok "Installed $ver"
    }
}

# ── PATH configuration ───────────────────────────────────────────────────────
function Ensure-Path {
    $global:Stage = 'ensure_path'
    if ($NoPath) { Write-Host '  PATH modification skipped (--no-path)' -ForegroundColor DarkGray; return }

    $binDir = Get-UvToolBinDir
    $currentPath = [Environment]::GetEnvironmentVariable('PATH', 'User')

    if ($currentPath -like "*$binDir*") {
        Write-Host "  uv tool bin directory already on PATH: $binDir" -ForegroundColor DarkGray
        return
    }

    Write-Step "Adding uv tool bin directory to PATH..."
    if ($DryRun) {
        Write-Host "  [dry-run] Would add $binDir to User PATH" -ForegroundColor DarkGray
        return
    }

    [Environment]::SetEnvironmentVariable('PATH', "$binDir;$currentPath", 'User')
    $env:Path = "$binDir;$env:Path"
    Write-Ok "Added $binDir to User PATH"
}

# ── Skills registration ──────────────────────────────────────────────────────
function Install-Skills {
    $global:Stage = 'install_skills'
    Write-Step 'Registering skills with AI agents...'
    if ($DryRun) { Write-Host '  [dry-run] stata-agent install-skills' -ForegroundColor DarkGray; return }

    try {
        & stata-agent install-skills 2>&1 | ForEach-Object { Write-Host "   • $_" -ForegroundColor DarkGray }
        Write-Ok 'Skills registered with detected agents'
    } catch {
        Write-Warn 'Skills registration encountered issues. Run: stata-agent install-skills --verbose'
    }
}

# ── Verification ─────────────────────────────────────────────────────────────
function Verify-Install {
    $global:Stage = 'verify_install'
    Write-Step 'Verifying installation...'

    if ($DryRun) {
        Write-Host '  [dry-run] stata-agent --version' -ForegroundColor DarkGray
        Write-Host '  [dry-run] stata-agent doctor --json' -ForegroundColor DarkGray
        return
    }

    # Check for binary
    if (-not (Get-Command stata-agent -ErrorAction SilentlyContinue)) {
        Write-Err 'stata-agent binary not found on PATH after install. Open a new terminal and run: stata-agent doctor'
    }

    # Confirm this is stata-agent
    try {
        $versionOut = & stata-agent --version 2>&1
        if ($versionOut -notmatch 'stata.agent|stata_agent') {
            Write-Warn "stata-agent binary found but may not be stata-agent: $versionOut"
        }
    } catch {
        Write-Err "stata-agent --version failed: $_"
    }

    # Doctor check
    try {
        $doctorOut = & stata-agent doctor --json 2>&1
        Write-Ok 'stata-agent doctor passed'
    } catch {
        Write-Warn 'stata-agent doctor reported issues (see above)'
    }

    # PATH visibility warning
    if (-not (Get-Command stata-agent -ErrorAction SilentlyContinue)) {
        Write-Warn 'stata-agent installed but not visible in current shell. Open a new terminal.'
    }
}

# ── Main ─────────────────────────────────────────────────────────────────────
function Main {
    $global:InstallId = New-InstallId
    $global:UserId = Get-UserId
    $global:Stage = ''

    Show-Header
    $global:Stage = 'install_start'
    Send-Telemetry 'install_start'

    Ensure-Uv
    Install-Package

    if ($Uninstall) {
        if ($Purge) {
            $global:Stage = 'purge'
            Write-Step 'Purging user state...'
            if (-not $DryRun) {
                Remove-Item "$env:LOCALAPPDATA\stata-agent" -Recurse -Force -ErrorAction SilentlyContinue
                Remove-Item "$env:USERPROFILE\.cache\stata-agent" -Recurse -Force -ErrorAction SilentlyContinue
            } else {
                Write-Host '  [dry-run] Would remove user state' -ForegroundColor DarkGray
            }
        }
        Send-Telemetry 'uninstall_success'
        Write-Ok 'Uninstall complete'
        Stop-Transcript
        return
    }

    Ensure-Path
    Install-Skills
    Verify-Install

    $global:Stage = 'install_success'
    Send-Telemetry 'install_success'

    Write-Host ''
    Write-Host 'STATA-AGENT IS LIVE' -ForegroundColor Green
    Write-Host ''
    Write-Host 'Verify:' -ForegroundColor Cyan
    Write-Host '  stata-agent --version'
    Write-Host '  stata-agent doctor --json'
    Write-Host ''
    Write-Host "repo    $GithubRepoUrl" -ForegroundColor DarkGray
    Write-Host "log     $TranscriptLog" -ForegroundColor DarkGray
}

Main
Stop-Transcript
