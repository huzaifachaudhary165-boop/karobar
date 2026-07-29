<#
.SYNOPSIS
  Builds Karobar and runs it on a USB-connected Android phone.

.DESCRIPTION
  The phone reaches the API over the USB cable rather than Wi-Fi, using
  `adb reverse`: the phone's own 127.0.0.1:8000 is forwarded to this machine's
  port 8000. That sidesteps two things that otherwise stop you —

    * Windows Firewall blocking inbound connections from the phone
      (your Wi-Fi is on the Public profile, where it is strictest), and
    * Android 9+ refusing plain HTTP to anything but an allow-listed address.

  The API must already be running in another terminal:

      cd backend
      uvicorn app.main:app --port 8000

.EXAMPLE
  .\scripts\run-on-phone.ps1
  .\scripts\run-on-phone.ps1 -Release
#>
param(
    # Debug is the default: it installs faster and supports hot reload with `r`.
    [switch]$Release,
    # Override when testing against a deployed server instead of this machine.
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api/v1",
    # Only needed if more than one phone is plugged in.
    [string]$DeviceId
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# ── adb ───────────────────────────────────────────────────────────
$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
if (-not $adb) {
    $candidates = @(
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
        "$env:ProgramFiles\Android\Android Studio\platform-tools\adb.exe",
        "$env:USERPROFILE\AppData\Local\Android\Sdk\platform-tools\adb.exe"
    )
    $adb = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $adb) {
    Write-Host "adb not found. Install Android platform-tools, or add it to PATH." -ForegroundColor Red
    exit 1
}

# ── the phone ─────────────────────────────────────────────────────
if (-not $DeviceId) {
    # @() matters: with exactly one device the pipeline yields a bare string, and
    # indexing a string returns its first *character* — the device id silently
    # becomes "R".
    $devices = @(
        & $adb devices | Select-Object -Skip 1 |
            Where-Object { $_ -match "\tdevice$" } |
            ForEach-Object { ($_ -split "\t")[0] }
    )

    if ($devices.Count -eq 0) {
        Write-Host "No phone detected." -ForegroundColor Red
        Write-Host "  Plug it in, unlock it, and allow USB debugging when prompted."
        exit 1
    }
    if ($devices.Count -gt 1) {
        Write-Host "More than one device attached. Pass -DeviceId:" -ForegroundColor Yellow
        $devices | ForEach-Object { Write-Host "  $_" }
        exit 1
    }
    $DeviceId = $devices[0]
}
Write-Host "Phone      : $DeviceId" -ForegroundColor Cyan

# ── is the API actually up? ───────────────────────────────────────
# Checked before building, because finding out after a three-minute build that
# the server was never started is the most annoying possible order.
if ($ApiBaseUrl -match "127\.0\.0\.1|localhost") {
    try {
        $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health/ready" `
                                    -TimeoutSec 5 -UseBasicParsing
        Write-Host "API        : up ($($health.StatusCode))" -ForegroundColor Cyan
    } catch {
        Write-Host "API is not running on port 8000." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Open another terminal and start it:" -ForegroundColor Yellow
        Write-Host "    cd $root\backend"
        Write-Host "    uvicorn app.main:app --port 8000"
        Write-Host ""
        exit 1
    }
}

# ── USB port forward ──────────────────────────────────────────────
# Re-applied every run: it is dropped whenever the cable is unplugged or the
# adb server restarts, and a stale forward looks exactly like a dead server.
& $adb -s $DeviceId reverse --remove tcp:8000 2>$null | Out-Null
& $adb -s $DeviceId reverse tcp:8000 tcp:8000 | Out-Null
Write-Host "Forward    : phone 127.0.0.1:8000 -> this machine" -ForegroundColor Cyan
Write-Host "API URL    : $ApiBaseUrl" -ForegroundColor Cyan
Write-Host ""

# ── run ───────────────────────────────────────────────────────────
$mode = if ($Release) { "--release" } else { "--debug" }
Push-Location "$root\mobile"
try {
    Write-Host "Building and installing... the first run takes a few minutes." -ForegroundColor Yellow
    Write-Host ""
    & flutter run $mode -d $DeviceId --dart-define=API_BASE_URL=$ApiBaseUrl
} finally {
    Pop-Location
}
