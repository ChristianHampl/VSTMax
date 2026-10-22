# AI Mix Engineer (AIME) für Cubase

Lokaler, kostenloser Mix- und Mastering-Assistent für Rock- und Metal-Produktionen. Läuft komplett
auf dem eigenen Rechner, ohne Cloud, ohne kostenpflichtige KI-APIs und ohne fremde Audio- oder
ML-Modelle.

- **Analyse & Rollenerkennung** jeder Spur (Kick, Snare, Gitarren-Doubles, Lead/Scream/Backing-Vocals …)
  mit Konfidenz; unsichere Fälle werden markiert und lassen sich von Hand korrigieren.
- **Mix-Plan** aus 8 Genre-Profilen (Alternative Rock, Hard Rock, Heavy Metal, Thrash, Death,
  Metalcore, Modern, Progressive) plus Klangcharakter (Helligkeit, Punch, Breite, Vocal-Pegel, Dynamik).
  Jede Entscheidung wird begründet und protokolliert.
- **Iterative Optimierung**: messen, eine Änderung, neu rendern, vergleichen, übernehmen oder verwerfen.
- **Mastering** mit LUFS-Ziel (BS.1770-4) und True-Peak-Grenze; Überkompression wird verhindert statt
  das Lautheitsziel zu erzwingen. **Referenzvergleich** und **Album-Modus** für einheitliche Alben.
- **Eigene VST3-Plug-ins** `AIME Channel`, `AIME Bus`, `AIME Master` (gleicher DSP wie die Offline-Engine).
- **Cubase-Automatik**: Plug-ins verbinden sich lokal mit der App (Plugin-Link). Die App nimmt die Spuren
  beim Abspielen auf, plant den Mix und schreibt alle Plug-in-Parameter zurück. Sends, Fader und
  Transport laufen optional über ein MIDI-Remote-Skript. Vor jedem Senden wird ein Snapshot angelegt
  (Rückgängig).
- **Ordnerüberwachung**: Stem-Exporte aus Cubase werden automatisch gemischt und gemastert.
- Originaldateien und Cubase-Projekte werden **nie** überschrieben; alle Ergebnisse landen in neuen Ordnern.

> Ehrlicher Stand: Siehe [STATUS.md](STATUS.md). Die Plug-ins sind unter Linux gebaut und mit dem
> offiziellen Steinberg-Validator geprüft. **In Cubase selbst und unter Windows wurde noch nichts
> ausgeführt.**

## Schnellstart (Windows 10/11)

1. Voraussetzungen installieren: [Python 3.11+](https://www.python.org/downloads/windows/),
   [Git](https://git-scm.com/download/win), Visual Studio 2022 Build Tools mit „Desktopentwicklung mit C++“
   (enthält CMake). Für MIDI Remote zusätzlich einen virtuellen MIDI-Treiber, z. B. loopMIDI.
2. In PowerShell im Projektordner:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\build.ps1            # holt das VST3 SDK, baut, testet, validiert
   powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1  # Python-Umgebung, Plug-in, MIDI-Remote-Skript
   ```
3. GUI starten: `scripts\start_gui.bat` oder `.venv\Scripts\python -m app gui`.

Ohne Cubase-Anbindung funktioniert der Datei-Workflow: Stems exportieren → in die App ziehen →
„Mischen, Mastern & Exportieren“. Dabei entstehen Mix, Master, Bus-Stems, Bericht, Presets (`.vstpreset`)
und ein Einrichtungsblatt für Cubase.

## Kommandozeile

```text
python -m app profiles                                   # Profile und Mastering-Zwecke
python -m app mix <Ordner|Dateien> --profile modern_metal --purpose streaming_loud --out <Ziel>
python -m app analyze <Ordner>                           # nur Analyse/Klassifikation als JSON
python -m app album song1.wav song2.wav --out <Ziel> --mode uniform
python -m app watch <Eingang> <Ausgang>                  # Ordnerüberwachung
python -m app autopilot --work <Arbeitsordner> [--midi]  # Cubase-Autopilot über die Plug-ins
python -m app autopilot --work <Arbeitsordner> --undo    # letzten Push rückgängig
```

## Dokumentation

| Thema | Datei |
|---|---|
| Bedienung | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| Cubase-Anbindung (Plugin-Link, MIDI Remote, Fallback) | [docs/CUBASE_INTEGRATION.md](docs/CUBASE_INTEGRATION.md) |
| Cubase-Vorlage einrichten | [docs/CUBASE_TEMPLATE.md](docs/CUBASE_TEMPLATE.md) |
| Architektur | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| DSP-Design der Plug-ins | [docs/DSP_DESIGN.md](docs/DSP_DESIGN.md) |
| Fehlerbehebung | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Drittanbieter & Lizenzen | [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md) |
| Teststand, Grenzen | [STATUS.md](STATUS.md) |

## Entwicklung (Linux/macOS)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
scripts/fetch_vst3sdk.sh        # oder VST3_SDK_ROOT=<pfad> setzen
CXX=g++ scripts/build.sh        # DSP-Tests, Plug-ins, Validator
scripts/run_tests.sh            # alle Tests (GUI headless)
```

Lizenz: MIT (siehe [LICENSE](LICENSE)). VST ist eine Marke der Steinberg Media Technologies GmbH.
