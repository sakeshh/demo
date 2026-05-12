# Generate HTML (and JSON/MD) report using local sample_data — no Azure/SQL required.
# Usage: from project root, run:  powershell -ExecutionPolicy Bypass -File scripts\run_html_report.ps1
# Requires: Python 3.10+ on PATH, pip install -r requirements.txt

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = $null
foreach ($c in @("python", "py")) {
    try {
        $ver = & $c --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python") { $py = $c; break }
    } catch { }
}
if (-not $py) {
    Write-Host "Python not found. Install from https://www.python.org/downloads/ and check 'Add to PATH'." -ForegroundColor Red
    exit 1
}

Write-Host "Using: $py $(& $py --version)"
& $py -m pip install -r requirements.txt -q
& $py main.py `
    --sources config/sources_local_run.yaml `
    --skip-azure `
    --evaluate all `
    --reports-dir output/reports

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$html = Join-Path $Root "output\reports\report.html"
Write-Host ""
Write-Host "Done. Open in browser:" -ForegroundColor Green
Write-Host $html
