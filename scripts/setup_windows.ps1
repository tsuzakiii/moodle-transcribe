# Windows setup: venv + deps + playwright browsers
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
    if (-not (Test-Path .venv)) {
        Write-Host "Creating venv (Python 3.12+ recommended)…"
        py -3 -m venv .venv
    }
    & .\.venv\Scripts\Activate.ps1
    pip install --upgrade pip
    pip install -e ".[gpu,remote]"
    python -m playwright install chromium

    $cfgDir = Join-Path $env:APPDATA "moodle-transcribe"
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    $cfg = Join-Path $cfgDir "config.toml"
    if (-not (Test-Path $cfg)) {
        Copy-Item config.example.toml $cfg
        Write-Host "Wrote default config to $cfg"
    }

    Write-Host "`nDone. Next:"
    Write-Host "  1. Place moodle_cookies.txt at $cfgDir"
    Write-Host "  2. (Optional) edit $cfg"
    Write-Host "  3. Set API keys:  `$env:OPENAI_API_KEY=`"...`""
    Write-Host "  4. Launch:  .\.venv\Scripts\python.exe -m moodle_transcribe.gui"
} finally {
    Pop-Location
}
