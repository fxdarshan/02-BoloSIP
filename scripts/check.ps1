# Run every BoloSIP check: unit tests, then the evaluation gates.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\check.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "== Unit tests" -ForegroundColor Cyan
python -m unittest discover tests
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: unit tests" -ForegroundColor Red; exit 1 }

Write-Host "== Evaluation gates" -ForegroundColor Cyan
python -m eval.run --all --no-write
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: evaluation gates" -ForegroundColor Red; exit 1 }

Write-Host "All checks passed." -ForegroundColor Green
