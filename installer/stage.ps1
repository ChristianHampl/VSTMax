# Legt installer\payload für den Windows-Installer an: das gebaute Plug-in und das MIDI-Skript.
# Aufruf nach scripts\build.ps1, aus dem Projektordner oder direkt.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$payload = Join-Path $PSScriptRoot "payload"
if (Test-Path $payload) { Remove-Item -Recurse -Force $payload }
New-Item -ItemType Directory -Path $payload | Out-Null

$src = Join-Path $root "build\plugins\VST3\Release\AIME.vst3"
if (-not (Test-Path (Join-Path $src "Contents"))) {
    throw "Windows-Plug-in nicht gefunden: $src  (zuerst scripts\build.ps1)"
}
Copy-Item -Recurse $src (Join-Path $payload "AIME.vst3")
Copy-Item (Join-Path $root "integration\midi_remote\AIME\Bridge\AIME_Bridge.js") (Join-Path $payload "AIME_Bridge.js")
Write-Host "Payload bereit: $payload"
