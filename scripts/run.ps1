$ErrorActionPreference = 'Stop'
$StudioRoot = Split-Path -Parent $PSScriptRoot
$StudioPython = Join-Path $StudioRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $StudioPython)) {
    $StudioPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (-not (Test-Path -LiteralPath $StudioPython)) {
        $StudioPython = (Get-Command python -ErrorAction Stop).Source
    }
}
& $StudioPython (Join-Path $PSScriptRoot 'studio.py') @args
exit $LASTEXITCODE
