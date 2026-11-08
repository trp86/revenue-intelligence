# Starts the whole web app: the API (revint serve, port 8000) and the frontend (Vite, port 5173),
# each in its own PowerShell window, then opens the browser.
#   .\start.ps1            start both
#   .\start.ps1 -Build     rebuild the warehouse first (uv run revint build all)
#   .\start.ps1 -NoBrowser do not open the browser
param(
    [switch]$Build,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Frontend = Join-Path $Root "frontend"
$ApiUrl = "http://127.0.0.1:8000/api/v1/health"
$WebUrl = "http://localhost:5173"

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Port($Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Host "Revenue Intelligence: starting the web app" -ForegroundColor Cyan

# 1. Tools
foreach ($tool in "uv", "npm") {
    if (-not (Test-Command $tool)) {
        Write-Host "  '$tool' was not found on PATH. Install it and try again." -ForegroundColor Red
        exit 1
    }
}

# 2. Python dependencies
Write-Host "  Checking Python dependencies (uv sync)..."
Push-Location $Root
try { uv sync --quiet } finally { Pop-Location }

# 3. Frontend dependencies (only when missing)
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Write-Host "  Installing frontend dependencies (npm install)..."
    Push-Location $Frontend
    try { npm install } finally { Pop-Location }
}

# 4. The warehouse
$Warehouse = Join-Path $Root "data\warehouse.duckdb"
if ($Build -or -not (Test-Path $Warehouse)) {
    Write-Host "  Building the warehouse (uv run revint build all); this can take a few minutes..."
    Push-Location $Root
    try { uv run revint build all } finally { Pop-Location }
}

# 5. Gemini key: only checks that the file exists, never reads or prints it
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host "  No .env file: the app works, but 'Generate brief' needs GEMINI_API_KEY in .env." -ForegroundColor Yellow
}

# 6. API window
if (Test-Port 8000) {
    Write-Host "  Port 8000 is already in use; assuming the API is running." -ForegroundColor Yellow
} else {
    Write-Host "  Starting the API on port 8000..."
    Start-Process powershell -WorkingDirectory $Root -ArgumentList @(
        "-NoExit", "-Command",
        "`$Host.UI.RawUI.WindowTitle = 'Revenue Intelligence API'; uv run revint serve"
    )
}

# 7. Frontend window
if (Test-Port 5173) {
    Write-Host "  Port 5173 is already in use; assuming the frontend is running." -ForegroundColor Yellow
} else {
    Write-Host "  Starting the frontend on port 5173..."
    Start-Process powershell -WorkingDirectory $Frontend -ArgumentList @(
        "-NoExit", "-Command",
        "`$Host.UI.RawUI.WindowTitle = 'Revenue Intelligence frontend'; npm run dev"
    )
}

# 8. Wait for the API, then open the browser
Write-Host "  Waiting for the API to answer..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        Invoke-WebRequest -Uri $ApiUrl -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if ($ready) {
    Write-Host "  API is up." -ForegroundColor Green
} else {
    Write-Host "  The API did not answer within 60 seconds; check the 'Revenue Intelligence API' window." -ForegroundColor Yellow
}

if (-not $NoBrowser) {
    Start-Sleep -Seconds 2
    Start-Process $WebUrl
}

Write-Host ""
Write-Host "Running:" -ForegroundColor Cyan
Write-Host "  App: $WebUrl"
Write-Host "  API: http://127.0.0.1:8000/docs"
Write-Host "To stop, close the two windows (or press Ctrl+C in each)."
