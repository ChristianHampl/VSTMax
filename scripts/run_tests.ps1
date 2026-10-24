# Alle automatischen Tests unter Windows (Python + nativ, falls gebaut).
# HINWEIS: Dieses Skript wurde in der Entwicklungsumgebung (Linux) nicht ausgeführt - siehe STATUS.md.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
if (Test-Path "build\dsp\Release\aime_dsp_tests.exe") {
    & build\dsp\Release\aime_dsp_tests.exe
    if ($LASTEXITCODE -ne 0) { throw "DSP-Tests fehlgeschlagen" }
}
& $py scripts\gen_params.py --check
if ($LASTEXITCODE -ne 0) { throw "Generierte Parameter veraltet (python scripts\gen_params.py)" }
$env:QT_QPA_PLATFORM = "offscreen"
& $py -m pytest -q @args
exit $LASTEXITCODE
