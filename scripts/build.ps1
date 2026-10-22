# Baut DSP-Kern + Tests und die VST3-Plug-ins (inkl. Steinberg-Validator) unter Windows 10/11.
# Voraussetzungen: Visual Studio 2022 (oder Build Tools) mit "Desktopentwicklung mit C++", CMake >= 3.25, Git.
# HINWEIS: Dieses Skript wurde in der Entwicklungsumgebung (Linux) nicht ausgeführt - siehe STATUS.md.
param([string]$Generator = "Visual Studio 17 2022")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "CMake nicht gefunden. Installation: Visual Studio Installer (C++-CMake-Tools) oder https://cmake.org/download/"
}

cmake -S dsp -B build/dsp -G $Generator -A x64
if ($LASTEXITCODE -ne 0) { throw "CMake-Konfiguration (dsp) fehlgeschlagen" }
cmake --build build/dsp --config Release
if ($LASTEXITCODE -ne 0) { throw "Build (dsp) fehlgeschlagen" }
ctest --test-dir build/dsp -C Release --output-on-failure
if ($LASTEXITCODE -ne 0) { throw "DSP-Tests fehlgeschlagen" }

if (-not $env:VST3_SDK_ROOT -and -not (Test-Path "external\vst3sdk\pluginterfaces")) {
    & (Join-Path $PSScriptRoot "fetch_vst3sdk.ps1")
}
cmake -S plugins -B build/plugins -G $Generator -A x64
if ($LASTEXITCODE -ne 0) { throw "CMake-Konfiguration (plugins) fehlgeschlagen" }
cmake --build build/plugins --config Release 2>&1 | Tee-Object -FilePath build/plugins/build.log
if ($LASTEXITCODE -ne 0) { throw "Build (plugins) fehlgeschlagen" }
$res = Select-String -Path build/plugins/build.log -Pattern "Result: \d+ tests passed, (\d+) tests failed"
foreach ($m in $res) {
    if ([int]$m.Matches[0].Groups[1].Value -ne 0) { throw "Steinberg-Validator meldet Fehler: $($m.Line)" }
}
Write-Host "Fertig: build\plugins\VST3\Release\AIME.vst3"
