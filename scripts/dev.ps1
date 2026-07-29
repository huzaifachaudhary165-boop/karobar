<#
.SYNOPSIS
  Karobar developer helper.

.EXAMPLE
  .\scripts\dev.ps1 setup     # install backend + mobile dependencies
  .\scripts\dev.ps1 seed      # rebuild the demo database
  .\scripts\dev.ps1 api       # run the backend with reload
  .\scripts\dev.ps1 app       # run the Flutter app
  .\scripts\dev.ps1 test      # backend tests + flutter analyze + flutter test
  .\scripts\dev.ps1 check     # configuration report
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'seed', 'api', 'app', 'test', 'check', 'migrate', 'reset')]
    [string]$Command = 'check'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$mobile = Join-Path $root 'mobile'
$env:PYTHONPATH = $backend

function Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }

switch ($Command) {
    'setup' {
        Step 'Installing backend dependencies'
        Push-Location $backend
        python -m pip install -r requirements.txt
        if (-not (Test-Path '.env')) {
            Copy-Item '.env.example' '.env'
            Write-Host 'Created backend/.env — add your SECRET_KEY and ANTHROPIC_API_KEY.' -ForegroundColor Yellow
        }
        Pop-Location

        Step 'Installing Flutter dependencies'
        Push-Location $mobile
        flutter pub get
        Pop-Location
    }

    'seed' {
        Step 'Rebuilding demo data'
        Push-Location $backend
        Remove-Item 'karobar.db' -Force -ErrorAction SilentlyContinue
        python -m app.cli seed
        Pop-Location
    }

    'api' {
        Step 'Starting the API on http://127.0.0.1:8000'
        Push-Location $backend
        python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
        Pop-Location
    }

    'app' {
        Step 'Starting the Flutter app'
        Push-Location $mobile
        flutter run
        Pop-Location
    }

    'test' {
        Step 'Backend tests'
        Push-Location $backend
        python -m pytest -q
        Pop-Location

        Step 'Flutter analyze'
        Push-Location $mobile
        flutter analyze
        Step 'Flutter tests'
        flutter test
        Pop-Location

        Write-Host "`nAll checks passed." -ForegroundColor Green
    }

    'migrate' {
        Step 'Applying database migrations'
        Push-Location $backend
        python -m alembic upgrade head
        Pop-Location
    }

    'reset' {
        Step 'Resetting the database'
        Push-Location $backend
        python -m app.cli reset
        Pop-Location
    }

    'check' {
        Push-Location $backend
        python -m app.cli check
        Pop-Location
    }
}
