param([Parameter(ValueFromRemainingArguments=$true)][string[]]$BoraArguments)

$ErrorActionPreference = 'Stop'
$runtimeBin = Join-Path $env:LOCALAPPDATA 'BoraDev/msys64/ucrt64/bin'
$pythonPath = Join-Path $runtimeBin 'python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Windows 개발 런타임이 없습니다. docs/research/2026-10-10-windows-runtime.md를 확인하세요.'
}
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$env:PATH = "$runtimeBin;$env:PATH"
$env:PYTHONPATH = "$(Join-Path $repoRoot 'src');$(Join-Path $env:LOCALAPPDATA 'BoraDev/python-packages')"
$env:PYTHONUTF8 = '1'
& $pythonPath -m bora @BoraArguments
exit $LASTEXITCODE
