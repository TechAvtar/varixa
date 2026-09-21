# Runs every CI check locally. Usage: scripts\check.ps1 [api|web]
param([ValidateSet("all","api","web")][string]$Target = "all")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Invoke-Step([string]$Cmd) {
  Write-Host ">> $Cmd"
  Invoke-Expression $Cmd
  if ($LASTEXITCODE -ne 0) { throw "Step failed: $Cmd" }
}

function Check-Api {
  Write-Host "== API"
  Push-Location "$Root\services\api"
  try {
    $py = ".\.venv\Scripts\python.exe"
    Invoke-Step "$py -m ruff check ."
    Invoke-Step "$py -m ruff format --check ."
    Invoke-Step "$py -m mypy app tests"
    $env:VERIXA_ENVIRONMENT = "test"
    Invoke-Step "$py -m pytest -q"
  } finally { Pop-Location }
}

function Check-Web {
  Write-Host "== Web"
  Push-Location $Root
  try {
    $env:NEXT_TELEMETRY_DISABLED = "1"
    Invoke-Step "npm run lint"
    Invoke-Step "npm run format:check"
    Invoke-Step "npm run typecheck"
    Invoke-Step "npm run build"
  } finally { Pop-Location }
}

switch ($Target) {
  "api" { Check-Api }
  "web" { Check-Web }
  default { Check-Api; Check-Web }
}
Write-Host "== All checks passed"
