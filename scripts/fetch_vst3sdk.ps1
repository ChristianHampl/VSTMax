# Lädt das offizielle Steinberg VST3 SDK (MIT-Lizenz) nach external\vst3sdk.
# Getesteter Stand: Tag v3.8.1_build_84 (unter Linux gebaut und validiert; Windows-Build siehe STATUS.md)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$tag = if ($env:VST3_SDK_TAG) { $env:VST3_SDK_TAG } else { "v3.8.1_build_84" }
if (Test-Path "external\vst3sdk\pluginterfaces") {
    Write-Host "external\vst3sdk ist bereits vorhanden - nichts zu tun."
    exit 0
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git nicht gefunden. Bitte Git für Windows installieren: https://git-scm.com/download/win"
}
New-Item -ItemType Directory -Force -Path external | Out-Null
git clone --branch $tag --depth 1 --recurse-submodules --shallow-submodules `
    https://github.com/steinbergmedia/vst3sdk.git external/vst3sdk
if ($LASTEXITCODE -ne 0) { throw "git clone fehlgeschlagen" }
Write-Host "VST3 SDK $tag liegt in external\vst3sdk"
