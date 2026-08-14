# Rebuilds the web app and refreshes what Vercel serves.
#
# The site in `public/` is committed rather than built on Vercel, because
# Vercel has no Flutter SDK and installing one on every deploy is minutes of
# build time for a folder that changes only when someone runs this.
#
#   .\build.ps1
#   .\build.ps1 -Api "http://127.0.0.1:8000/api/v1"   # against a local backend
#
# Then commit `public/` and push. Vercel deploys the folder as it stands.

param(
  [string]$Api = "https://karobar-e24a.vercel.app/api/v1"
)

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$mobile = Join-Path $root "mobile"
$public = Join-Path $PSScriptRoot "public"

Write-Host "Building Karobar for the web" -ForegroundColor Cyan
Write-Host "  API: $Api"

Push-Location $mobile
try {
  $stamp = Get-Date -Format "yyyy-MM-dd-HHmm"
  flutter build web --release --no-wasm-dry-run `
    --dart-define=API_BASE_URL=$Api `
    --dart-define=BUILD_STAMP=$stamp
  if ($LASTEXITCODE -ne 0) { throw "flutter build web failed" }
} finally {
  Pop-Location
}

# Replaced wholesale, not merged: a file dropped from the build has to
# disappear from what is served, or the site keeps serving something the app no
# longer knows about.
if (Test-Path $public) { Remove-Item $public -Recurse -Force }
New-Item -ItemType Directory -Path $public -Force | Out-Null
Copy-Item (Join-Path $mobile "build\web\*") $public -Recurse -Force

$files = Get-ChildItem $public -Recurse -File
Write-Host ("Ready: {0} files, {1:N1} MB in webapp\public" -f `
  $files.Count, (($files | Measure-Object Length -Sum).Sum / 1MB)) -ForegroundColor Green
Write-Host "Now: git add webapp && git commit && git push"
