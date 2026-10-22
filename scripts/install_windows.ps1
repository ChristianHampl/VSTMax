# Installiert AIME.vst3 und das MIDI-Remote-Skript für Cubase und richtet die Python-Umgebung ein.
# - Plug-in: C:\Program Files\Common Files\VST3\AIME.vst3 (Administratorrechte nötig)
# - MIDI Remote: <Dokumente>\Steinberg\Cubase\MIDI Remote\Driver Scripts\Local\AIME\Bridge\
# Es werden ausschließlich AIME-eigene Dateien ersetzt, und das nur nach Rückfrage.
# HINWEIS: Dieses Skript wurde in der Entwicklungsumgebung (Linux) nicht ausgeführt - siehe STATUS.md.
param([switch]$SkipPlugin, [switch]$SkipMidiRemote, [switch]$SkipPython, [switch]$Yes)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")

function Confirm-Replace([string]$path) {
    if (-not (Test-Path $path)) { return $true }
    if ($Yes) { return $true }
    $a = Read-Host "$path existiert bereits. Ersetzen? (j/N)"
    return $a -match '^(j|ja|y|yes)$'
}

if (-not $SkipPython) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python-Launcher 'py' nicht gefunden. Python 3.11+ von https://www.python.org/downloads/windows/ installieren." }
    Push-Location $root
    if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt python-rtmidi
    Pop-Location
}

if (-not $SkipPlugin) {
    $src = Join-Path $root "build\plugins\VST3\Release\AIME.vst3"
    if (-not (Test-Path $src)) { throw "AIME.vst3 nicht gefunden - zuerst scripts\build.ps1 ausführen." }
    $dstDir = Join-Path $env:CommonProgramFiles "VST3"
    $dst = Join-Path $dstDir "AIME.vst3"
    if (Confirm-Replace $dst) {
        New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Copy-Item -Recurse $src $dst
        Write-Host "Plug-in installiert: $dst"
    }
}

if (-not $SkipMidiRemote) {
    $docs = [Environment]::GetFolderPath("MyDocuments")
    $dst = Join-Path $docs "Steinberg\Cubase\MIDI Remote\Driver Scripts\Local\AIME\Bridge"
    $file = Join-Path $dst "AIME_Bridge.js"
    if (Confirm-Replace $file) {
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Copy-Item -Force (Join-Path $root "integration\midi_remote\AIME\Bridge\AIME_Bridge.js") $file
        Write-Host "MIDI-Remote-Skript installiert: $file"
    }
    Write-Host ""
    Write-Host "Für MIDI Remote zwei virtuelle Ports anlegen (z. B. mit loopMIDI, kostenlos):"
    Write-Host "  'AIME to Cubase' und 'AIME from Cubase'"
    Write-Host "Danach Cubase neu starten oder im MIDI Remote Manager 'Skripte neu laden'."
}
