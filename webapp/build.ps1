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

# Emptied rather than deleted and recreated. A file dropped from the build has
# to disappear from what is served, or the site keeps serving something the app
# no longer knows about — but Windows refuses to remove a directory anything
# has open, and a terminal left sitting in `public` is enough to stop the whole
# build.
if (Test-Path $public) {
  Get-ChildItem $public -Force | Remove-Item -Recurse -Force
} else {
  New-Item -ItemType Directory -Path $public -Force | Out-Null
}
Copy-Item (Join-Path $mobile "build\web\*") $public -Recurse -Force

# Symbol maps for the rendering engine, used to turn a crash address back into
# a function name while profiling. A release build never fetches them, and at
# 7 MB a rebuild they are the largest thing this folder would add to the
# repository's history for no one's benefit.
$symbols = Get-ChildItem $public -Recurse -File -Filter "*.symbols"
if ($symbols) {
  $freed = ($symbols | Measure-Object Length -Sum).Sum / 1MB
  $symbols | Remove-Item -Force
  Write-Host ("  dropped {0} engine symbol files ({1:N1} MB)" -f $symbols.Count, $freed)
}

$files = Get-ChildItem $public -Recurse -File
Write-Host ("Ready: {0} files, {1:N1} MB in webapp\public" -f `
  $files.Count, (($files | Measure-Object Length -Sum).Sum / 1MB)) -ForegroundColor Green
Write-Host "Now: git add webapp && git commit && git push"
